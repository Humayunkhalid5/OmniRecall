# Licenses of the libraries bundled with Tesseract

The macOS installer ships Tesseract with the Homebrew libraries it loads (D-037). `scripts/package_engine.py` copies each keg's own license files into `engine/tesseract/licenses/`, and uses the folders here when a keg has none.

Windows no longer uses these folders (D-042, OR-030). Its `tesseract.exe` is a static vcpkg build (`scripts/build_tesseract_windows.py`) with ten permissive libraries linked in: Leptonica, giflib, libjpeg-turbo, libpng, libspng, libwebp, OpenJPEG, LibTIFF, liblzma, and zlib. Their `copyright` files come from vcpkg and are bundled the same way, and the build fails if a library outside the reviewed list appears. The Windows DLL column below records the UB Mannheim build the Phase 6 installers shipped.

Texts were fetched from the upstream repositories on 2026-10-22 (GNU license texts from the SPDX license list, because the GNU servers were unreachable from the build environment).

| Folder | Library | Windows DLL | License | Source of the text |
|---|---|---|---|---|
| `tesseract` | Tesseract OCR | libtesseract-5.dll, tesseract.exe | Apache-2.0 | github.com/tesseract-ocr/tesseract |
| `leptonica` | Leptonica | libleptonica-6.dll | BSD-2-Clause (Leptonica) | github.com/DanBloomberg/leptonica |
| `libarchive` | libarchive | libarchive-13.dll | BSD-2-Clause | github.com/libarchive/libarchive |
| `libb2` | BLAKE2 | libb2-1.dll | CC0-1.0 OR OpenSSL OR Apache-2.0 | github.com/BLAKE2/libb2 |
| `brotli` | Brotli | libbrotlicommon.dll, libbrotlidec.dll | MIT | github.com/google/brotli |
| `bzip2` | bzip2 | libbz2-1.dll | bzip2-1.0.6 | gitlab.com/bzip2/bzip2 |
| `curl` | libcurl | libcurl-4.dll | curl | github.com/curl/curl |
| `libdeflate` | libdeflate | libdeflate.dll | MIT | github.com/ebiggers/libdeflate |
| `expat` | Expat | libexpat-1.dll | MIT | github.com/libexpat/libexpat |
| `gcc-runtime` | GCC runtime libraries | libgcc_s_seh-1.dll, libstdc++-6.dll | GPL-3.0-or-later WITH GCC-exception-3.1 | github.com/gcc-mirror/gcc |
| `giflib` | giflib | libgif-7.dll | MIT | sourceforge.net/p/giflib |
| `libiconv` | GNU libiconv | libiconv-2.dll | LGPL-2.1-or-later | SPDX text |
| `libidn2` | libidn2 | libidn2-0.dll | LGPL-3.0-or-later OR GPL-2.0-or-later | gitlab.com/libidn/libidn2 |
| `gettext-intl` | GNU gettext runtime (libintl) | libintl-8.dll | LGPL-2.1-or-later | SPDX text |
| `jbigkit` | JBIG-KIT | libjbig-0.dll | GPL-2.0-or-later | SPDX text |
| `libjpeg-turbo` | libjpeg-turbo | libjpeg-8.dll | IJG AND BSD-3-Clause AND Zlib | github.com/libjpeg-turbo/libjpeg-turbo |
| `lerc` | LERC | libLerc.dll | Apache-2.0 | github.com/Esri/lerc |
| `lz4` | LZ4 library | liblz4.dll | BSD-2-Clause | github.com/lz4/lz4 |
| `xz` | XZ Utils (liblzma) | liblzma-5.dll | 0BSD | github.com/tukaani-project/xz |
| `openjpeg` | OpenJPEG | libopenjp2-7.dll | BSD-2-Clause | github.com/uclouvain/openjpeg |
| `libpng` | libpng | libpng16-16.dll | libpng-2.0 | github.com/pnggroup/libpng |
| `libpsl` | libpsl | libpsl-5.dll | MIT | github.com/rockdaboot/libpsl |
| `libwebp` | libwebp, libsharpyuv | libwebp-7.dll, libwebpmux-3.dll, libsharpyuv-0.dll | BSD-3-Clause, with a patent grant | github.com/webmproject/libwebp |
| `libssh2` | libssh2 | libssh2-1.dll | BSD-3-Clause | github.com/libssh2/libssh2 |
| `libtiff` | LibTIFF | libtiff-6.dll | libtiff | gitlab.com/libtiff/libtiff |
| `libunistring` | GNU libunistring | libunistring-5.dll | LGPL-3.0-or-later OR GPL-2.0-or-later | SPDX text |
| `winpthreads` | mingw-w64 winpthreads | libwinpthread-1.dll | MIT AND BSD-3-Clause | github.com/mirror/mingw-w64 |
| `zstd` | Zstandard | libzstd.dll | BSD-3-Clause OR GPL-2.0-only | github.com/facebook/zstd |
| `zlib` | zlib | zlib1.dll | Zlib | github.com/madler/zlib |

The copyleft entries (JBIG-KIT under the GPL; libiconv, libintl, libidn2, and libunistring under the LGPL) are separate shared libraries that the UB Mannheim Tesseract build loads (JBIG-KIT through LibTIFF, the others through libcurl). OmniRecall runs Tesseract as a separate program and does not link to any of them. Their source code is available from each upstream above; the UB Mannheim build is described at github.com/UB-Mannheim/tesseract/wiki. They were dropped by the static build (OR-030, fixed).
