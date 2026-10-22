//! Decodes one local audio file to 16 kHz mono 32-bit float PCM for transcription.
//!
//! The engine runs this as a child process (D-031), like Tesseract for OCR:
//!
//! ```text
//! omnirecall-audio-decode probe  <path>                  # one JSON line on stdout
//! omnirecall-audio-decode decode <path> <max-seconds>    # raw f32 little-endian on stdout
//! ```
//!
//! Errors are one JSON line on stderr, `{"code": "...", "message": "..."}`, and a
//! non-zero exit. The file is untrusted input: decoding is pure Rust (Symphonia),
//! only the named local file is opened, and nothing is fetched from anywhere.
//! Decoding stops as soon as the audio runs past the duration limit.

use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::process::ExitCode;

use rubato::audioadapter_buffers::direct::InterleavedSlice;
use rubato::{Fft, FixedSync, Indexing, Resampler};
use symphonia::core::codecs::audio::AudioDecoderOptions;
use symphonia::core::errors::Error as SymError;
use symphonia::core::formats::probe::Hint;
use symphonia::core::formats::{FormatOptions, FormatReader, TrackType};
use symphonia::core::io::{MediaSourceStream, MediaSourceStreamOptions};
use symphonia::core::meta::MetadataOptions;

const TARGET_RATE: usize = 16_000;
const CHUNK_FRAMES: usize = 4096;

#[derive(Debug)]
struct Failure {
    code: &'static str,
    message: String,
}

impl Failure {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

fn from_symphonia(err: SymError) -> Failure {
    match err {
        SymError::Unsupported(what) => Failure::new(
            "unsupported_codec",
            format!("This audio encoding is not supported ({what})"),
        ),
        SymError::IoError(e) if e.kind() == io::ErrorKind::UnexpectedEof => {
            Failure::new("malformed_file", "The audio file ends unexpectedly")
        }
        SymError::IoError(_) => Failure::new("malformed_file", "The audio file could not be read"),
        SymError::LimitError(_) => Failure::new("limit_exceeded", "The audio file is too large"),
        _ => Failure::new("malformed_file", "The audio file could not be decoded"),
    }
}

struct Opened {
    reader: Box<dyn FormatReader>,
    track_id: u32,
    sample_rate: u32,
    channels: usize,
    codec: String,
    duration_s: Option<f64>,
}

fn open(path: &Path) -> Result<Opened, Failure> {
    let file = File::open(path)
        .map_err(|_| Failure::new("source_missing", "The audio file could not be opened"))?;
    let mss = MediaSourceStream::new(Box::new(file), MediaSourceStreamOptions::default());
    let mut hint = Hint::new();
    if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
        hint.with_extension(ext);
    }
    let reader = symphonia::default::get_probe()
        .probe(
            &hint,
            mss,
            FormatOptions::default(),
            MetadataOptions::default(),
        )
        .map_err(|err| match err {
            // The engine only passes files with a supported extension, so a file no
            // reader recognises is damaged or misnamed.
            SymError::Unsupported(_) => Failure::new(
                "malformed_file",
                "The audio file is damaged or is not the type its name says",
            ),
            other => from_symphonia(other),
        })?;
    let track = reader
        .default_track(TrackType::Audio)
        .or_else(|| reader.first_track(TrackType::Audio))
        .ok_or_else(|| Failure::new("extraction_empty", "The file has no audio track"))?;
    let params = track
        .codec_params
        .as_ref()
        .and_then(|p| p.audio())
        .ok_or_else(|| Failure::new("unsupported_codec", "The audio track cannot be decoded"))?;
    let sample_rate = params
        .sample_rate
        .ok_or_else(|| Failure::new("malformed_file", "The audio track has no sample rate"))?;
    let channels = params
        .channels
        .as_ref()
        .map(|c| c.count())
        .unwrap_or(1)
        .max(1);
    let duration_s = match (track.time_base, track.duration) {
        (Some(tb), Some(dur)) => tb.calc_duration(dur).map(|t| t.as_secs_f64()),
        _ => track.num_frames.map(|n| n as f64 / f64::from(sample_rate)),
    };
    let codec = symphonia::default::get_codecs()
        .get_audio_decoder(params.codec)
        .map(|c| c.codec.info.short_name.to_string())
        .ok_or_else(|| Failure::new("unsupported_codec", "This audio encoding is not supported"))?;
    Ok(Opened {
        track_id: track.id,
        sample_rate,
        channels,
        codec,
        duration_s,
        reader,
    })
}

fn probe(path: &Path) -> Result<(), Failure> {
    let opened = open(path)?;
    let info = serde_json::json!({
        "duration_s": opened.duration_s,
        "sample_rate": opened.sample_rate,
        "channels": opened.channels,
        "codec": opened.codec,
    });
    println!("{info}");
    Ok(())
}

/// Streams 16 kHz mono samples to `out`, resampling when the source rate differs.
struct Output<W: Write> {
    out: W,
    resampler: Option<Fft<f32>>,
    pending: Vec<f32>,
    scratch: Vec<f32>,
    to_skip: usize,
    source_rate: u32,
    input_frames: u64,
    written: u64,
}

impl<W: Write> Output<W> {
    fn new(out: W, source_rate: u32) -> Result<Self, Failure> {
        let resampler = if source_rate as usize == TARGET_RATE {
            None
        } else {
            Some(
                Fft::<f32>::new(
                    source_rate as usize,
                    TARGET_RATE,
                    CHUNK_FRAMES,
                    1,
                    FixedSync::Input,
                )
                .map_err(|_| {
                    Failure::new(
                        "unsupported_codec",
                        "The audio sample rate is not supported",
                    )
                })?,
            )
        };
        let (scratch, to_skip) = match &resampler {
            Some(r) => (vec![0.0; r.output_frames_max()], r.output_delay()),
            None => (Vec::new(), 0),
        };
        Ok(Self {
            out,
            resampler,
            pending: Vec::new(),
            scratch,
            to_skip,
            source_rate,
            input_frames: 0,
            written: 0,
        })
    }

    fn emit(&mut self, mut samples: &[f32]) -> io::Result<()> {
        if self.to_skip > 0 {
            let skip = self.to_skip.min(samples.len());
            self.to_skip -= skip;
            samples = &samples[skip..];
        }
        let mut bytes = Vec::with_capacity(samples.len() * 4);
        for sample in samples {
            bytes.extend_from_slice(&sample.clamp(-1.0, 1.0).to_le_bytes());
        }
        self.written += samples.len() as u64;
        self.out.write_all(&bytes)
    }

    fn push(&mut self, mono: &[f32]) -> Result<(), Failure> {
        self.input_frames += mono.len() as u64;
        if self.resampler.is_none() {
            return self.emit(mono).map_err(write_failed);
        }
        self.pending.extend_from_slice(mono);
        loop {
            let needed = self
                .resampler
                .as_ref()
                .map_or(usize::MAX, |r| r.input_frames_next());
            if self.pending.len() < needed {
                return Ok(());
            }
            let produced = self.run(needed, None)?;
            self.pending.drain(..needed);
            let chunk = self.scratch[..produced].to_vec();
            self.emit(&chunk).map_err(write_failed)?;
        }
    }

    fn run(&mut self, frames: usize, partial: Option<usize>) -> Result<usize, Failure> {
        let resampler = self.resampler.as_mut().expect("resampler present");
        let input = InterleavedSlice::new(&self.pending[..frames], 1, frames)
            .map_err(|_| resample_failed())?;
        let capacity = self.scratch.len();
        let mut output = InterleavedSlice::new_mut(&mut self.scratch, 1, capacity)
            .map_err(|_| resample_failed())?;
        let indexing = Indexing {
            input_offset: 0,
            output_offset: 0,
            partial_len: partial,
            active_channels_mask: None,
        };
        let (_, produced) = resampler
            .process_into_buffer(&input, &mut output, Some(&indexing))
            .map_err(|_| resample_failed())?;
        Ok(produced)
    }

    fn finish(mut self) -> Result<(), Failure> {
        if self.resampler.is_some() {
            let expected = (self.input_frames as f64 * TARGET_RATE as f64
                / f64::from(self.source_rate))
            .round() as u64;
            // Feed the tail, then silence, until the delayed output has all come out.
            let mut guard = 0;
            while self.written < expected && guard < 64 {
                guard += 1;
                let needed = self.resampler.as_ref().map_or(0, |r| r.input_frames_next());
                let have = self.pending.len().min(needed);
                self.pending.resize(needed, 0.0);
                let produced = self.run(needed, Some(have))?;
                self.pending.clear();
                let room = (expected - self.written) as usize;
                let chunk = self.scratch[..produced.min(room + self.to_skip)].to_vec();
                self.emit(&chunk).map_err(write_failed)?;
            }
        }
        self.out.flush().map_err(write_failed)
    }
}

fn write_failed(_: io::Error) -> Failure {
    // The engine closed the pipe (for example, the user cancelled).
    Failure::new("cancelled", "Decoding stopped")
}

fn resample_failed() -> Failure {
    Failure::new("malformed_file", "The audio could not be resampled")
}

fn decode(path: &Path, max_seconds: f64) -> Result<(), Failure> {
    let mut opened = open(path)?;
    if let Some(duration) = opened.duration_s {
        if duration > max_seconds {
            return Err(Failure::new(
                "limit_exceeded",
                "The recording is longer than the limit",
            ));
        }
    }
    let params = opened
        .reader
        .tracks()
        .iter()
        .find(|t| t.id == opened.track_id)
        .and_then(|t| t.codec_params.clone());
    let params = params
        .as_ref()
        .and_then(|p| p.audio())
        .ok_or_else(|| Failure::new("unsupported_codec", "The audio track cannot be decoded"))?
        .clone();
    let mut decoder = symphonia::default::get_codecs()
        .make_audio_decoder(&params, &AudioDecoderOptions::default())
        .map_err(from_symphonia)?;
    let max_frames = (max_seconds * f64::from(opened.sample_rate)) as u64;
    let stdout = io::stdout();
    let mut output = Output::new(
        BufWriter::with_capacity(1 << 16, stdout.lock()),
        opened.sample_rate,
    )?;
    let mut interleaved: Vec<f32> = Vec::new();
    let mut mono: Vec<f32> = Vec::new();
    let mut decoded_frames: u64 = 0;
    let mut bad_packets = 0u32;
    loop {
        let packet = match opened.reader.next_packet() {
            Ok(Some(packet)) => packet,
            Ok(None) => break,
            Err(SymError::IoError(e)) if e.kind() == io::ErrorKind::UnexpectedEof => break,
            Err(err) => return Err(from_symphonia(err)),
        };
        if packet.track_id != opened.track_id {
            continue;
        }
        let buffer = match decoder.decode(&packet) {
            Ok(buffer) => buffer,
            // A damaged packet is skipped; a file that is mostly damage fails.
            Err(SymError::DecodeError(_)) => {
                bad_packets += 1;
                if bad_packets > 1000 {
                    return Err(Failure::new(
                        "malformed_file",
                        "The audio file is badly damaged",
                    ));
                }
                continue;
            }
            Err(err) => return Err(from_symphonia(err)),
        };
        let channels = buffer.spec().channels().count().max(1);
        buffer.copy_to_vec_interleaved(&mut interleaved);
        mono.clear();
        mono.extend(
            interleaved
                .chunks_exact(channels)
                .map(|frame| frame.iter().sum::<f32>() / channels as f32),
        );
        decoded_frames += mono.len() as u64;
        if decoded_frames > max_frames {
            return Err(Failure::new(
                "limit_exceeded",
                "The recording is longer than the limit",
            ));
        }
        output.push(&mono)?;
    }
    if decoded_frames == 0 {
        return Err(Failure::new(
            "extraction_empty",
            "The audio file contains no sound",
        ));
    }
    output.finish()
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let result = match args.get(1).map(String::as_str) {
        Some("probe") if args.len() == 3 => probe(Path::new(&args[2])),
        Some("decode") if args.len() == 4 => match args[3].parse::<f64>() {
            Ok(limit) if limit.is_finite() && limit > 0.0 => decode(Path::new(&args[2]), limit),
            _ => Err(Failure::new(
                "invalid_params",
                "The duration limit is not a positive number",
            )),
        },
        Some("--version") => {
            println!("{}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        _ => Err(Failure::new(
            "invalid_params",
            "usage: omnirecall-audio-decode probe <path> | decode <path> <max-seconds>",
        )),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => {
            let line = serde_json::json!({"code": failure.code, "message": failure.message});
            eprintln!("{line}");
            ExitCode::from(2)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn resample(rate: u32, input: &[f32]) -> Vec<f32> {
        let mut buffer = Vec::new();
        let mut output = Output::new(&mut buffer, rate).unwrap();
        for chunk in input.chunks(1000) {
            output.push(chunk).unwrap();
        }
        output.finish().unwrap();
        buffer
            .as_chunks::<4>()
            .0
            .iter()
            .map(|b| f32::from_le_bytes(*b))
            .collect()
    }

    #[test]
    fn passes_16k_audio_through() {
        let input: Vec<f32> = (0..16_000)
            .map(|i| (i as f32 / 100.0).sin() * 0.5)
            .collect();
        assert_eq!(resample(16_000, &input), input);
    }

    #[test]
    fn resamples_to_the_expected_length_and_pitch() {
        for rate in [8_000u32, 22_050, 44_100, 48_000] {
            let seconds = 2.0;
            let tone = 440.0;
            let input: Vec<f32> = (0..(seconds * rate as f32) as usize)
                .map(|i| (2.0 * std::f32::consts::PI * tone * i as f32 / rate as f32).sin() * 0.5)
                .collect();
            let out = resample(rate, &input);
            assert_eq!(out.len(), 32_000, "rate {rate}");
            // Zero crossings in the middle second match a 440 Hz tone at 16 kHz.
            let middle = &out[8_000..24_000];
            let crossings = middle
                .windows(2)
                .filter(|w| (w[0] < 0.0) != (w[1] < 0.0))
                .count();
            assert!((870..=890).contains(&crossings), "rate {rate}: {crossings}");
        }
    }
}
