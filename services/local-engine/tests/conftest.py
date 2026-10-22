import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Use the audio decoder built from services/audio-decoder when no other is set.
# CI builds it first and sets OMNIRECALL_REQUIRE_AUDIO_DECODER, so decoder tests
# can never silently skip there.
_DECODER_EXE = (
    Path(__file__).parents[2]
    / "audio-decoder"
    / "target"
    / "release"
    / ("omnirecall-audio-decode.exe" if sys.platform == "win32" else "omnirecall-audio-decode")
)
if _DECODER_EXE.is_file():
    os.environ.setdefault("OMNIRECALL_AUDIO_DECODER", str(_DECODER_EXE))
elif os.environ.get("OMNIRECALL_REQUIRE_AUDIO_DECODER") and not os.environ.get(
    "OMNIRECALL_AUDIO_DECODER"
):
    raise RuntimeError("OMNIRECALL_REQUIRE_AUDIO_DECODER is set but the decoder is not built")
