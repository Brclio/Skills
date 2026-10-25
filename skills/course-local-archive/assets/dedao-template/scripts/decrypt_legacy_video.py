#!/usr/bin/env python3
"""Reproduce the official native v1 media transform for authorized local files.

Input is a private 0600 JSON file with videos[{lesson_id, token}]. No keys,
tokens, account cookies, user IDs, or device IDs are logged or persisted.
Static RSA parameters are read transiently from the verified official library.
Original files and the independently obtained Web HLS MP4s remain unchanged.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "raw/official-player-package/extracted/lib/arm64-v8a/libddd_ff_protocol.so"
REPORT = ROOT / "raw/legacy-video-decryption-report.json"


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def library_slice(binary, address, size):
    phoff = struct.unpack_from("<Q", binary, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", binary, 54)
    for i in range(phnum):
        kind, flags, offset, va, pa, filesz, memsz, align = struct.unpack_from("<IIQQQQQQ", binary, phoff + i * phentsize)
        if kind == 1 and va <= address and address + size <= va + filesz:
            position = offset + address - va
            return binary[position:position + size], position
    raise ValueError("Official library parameter address is outside a file-backed segment")


def public_wrapper_parameters():
    binary = LIB.read_bytes()
    masked, parameter_file_offset = library_slice(binary, 0x5D010, 272)
    table, table_file_offset = library_slice(binary, 0x5D220, 256)
    unmasked = bytes(table[(((b ^ 0xA9) << 4) | ((b ^ 0xA9) >> 4)) & 255] for b in masked)
    n_match = re.search(rb"\bN\s*=\s*([0-9A-Fa-f]+)", unmasked)
    e_match = re.search(rb"\bE\s*=\s*([0-9A-Fa-f]+)", unmasked)
    if not n_match or not e_match:
        raise ValueError("Official v1 RSA parameter decoding did not match its native layout")
    modulus = int(n_match[1], 16)
    exponent = int(e_match[1], 16)
    try:
        library_path = LIB.relative_to(ROOT).as_posix()
    except ValueError:
        library_path = str(LIB)
    evidence = {"library": library_path, "library_sha256": sha_file(LIB), "parameter_va": "0x5d010", "parameter_file_offset": hex(parameter_file_offset), "substitution_table_va": "0x5d220", "substitution_table_file_offset": hex(table_file_offset), "parameter_encoding_sha256": hashlib.sha256(unmasked).hexdigest(), "rsa_modulus_bits": modulus.bit_length(), "unmask_function": "0xfc50", "v1_outer_consumer": "0xef68", "v1_check": "0xf064", "content_function": "0x1d7e0", "md5_functions": ["0x2021c", "0x20240", "0x20d58"], "aes128_key_schedule": "0x1f8fc", "ctr_xor_function": "0x1db70", "counter_increment_function": "0x1da3c"}
    return modulus, exponent, evidence


def unpack_token(token, modulus, exponent):
    outer = json.loads(base64.b64decode(token, validate=True))
    if outer.get("v") != 1:
        raise ValueError("Only the observed official v1 media wrapper is supported")
    wrapped = base64.b64decode(outer["tk"], validate=True)
    width = (modulus.bit_length() + 7) // 8
    if len(wrapped) != width:
        raise ValueError("Wrapped media token length does not match its official RSA modulus")
    block = pow(int.from_bytes(wrapped, "big"), exponent, modulus).to_bytes(width, "big")
    if block[:2] not in (b"\x00\x01", b"\x00\x02"):
        raise ValueError("Official public exponent did not recover a PKCS#1 wrapper")
    separator = block.find(b"\x00", 2)
    if separator < 10:
        raise ValueError("Recovered PKCS#1 padding is too short")
    inner = json.loads(block[separator + 1:])
    if not all(k in inner for k in ("k", "u", "d", "t")):
        raise ValueError("Recovered token did not have the official four-field media schema")
    key_bytes = base64.b64decode(inner["k"], validate=True)
    if len(key_bytes) < 16:
        raise ValueError("Recovered media key is shorter than its native AES-128 consumption")
    return key_bytes, {"outer_version": 1, "wrapped_bytes": width, "padding_type": block[1], "inner_field_names": sorted(inner), "decoded_media_key_bytes": len(key_bytes)}


class NativeAES128:
    """The OS's standard AES block primitive; the native counter logic is ours."""
    def __init__(self, key):
        self.key = key[:16]
        self.library = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")
        self.crypt = self.library.CCCrypt
        self.crypt.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.crypt.restype = ctypes.c_int

    def encrypt_blocks(self, data):
        if len(data) % 16:
            raise ValueError("AES block input must be a multiple of 16 bytes")
        result = ctypes.create_string_buffer(len(data) + 16)
        moved = ctypes.c_size_t()
        status = self.crypt(0, 0, 2, self.key, len(self.key), None, data, len(data), result, len(result), ctypes.byref(moved))
        if status != 0 or moved.value != len(data):
            raise ValueError("The OS AES block operation failed")
        return result.raw[:moved.value]


def transform_blocks(ciphertext, key_bytes, offset=0):
    if offset % 16:
        raise ValueError("Media source offsets must be block aligned")
    digest = hashlib.md5(key_bytes).digest()
    seed = bytes(((b ^ 6) + 5) & 255 for b in digest)
    prefix, suffix = seed[:4], seed[4:12]
    start = offset // 16
    counters = b"".join(prefix + ((start + i) & 0xFFFFFFFF).to_bytes(4, "big") + suffix for i in range((len(ciphertext) + 15) // 16))
    stream = NativeAES128(key_bytes).encrypt_blocks(counters)
    return bytes(a ^ b for a, b in zip(ciphertext, stream))


def run(args, timeout=900):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr[:6000]}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "Local media validation timed out"}


def streamhash(media, normalize_h264_vcl=False):
    args = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(media), "-map", "0:v", "-map", "0:a", "-c", "copy"]
    if normalize_h264_vcl:
        # Container/TS packaging adds non-picture NAL units. Compare identical
        # compressed picture slices plus unchanged compressed audio packets.
        args += ["-bsf:v", "h264_mp4toannexb,filter_units=pass_types=1-5"]
    h = run(args + ["-f", "streamhash", "-hash", "sha256", "-"])
    return {"returncode": h["returncode"], "streamhash": h["stdout"].strip(), "stderr": h["stderr"]}


def normalized_stream_comparison(path, reference):
    original = streamhash(path, True)
    other = streamhash(reference, True)
    return {"decrypted_original": original, "web_hls_remux": other, "normalization": "H264 to Annex B; retain picture VCL NAL types 1-5; preserve complete compressed audio packets", "exact_vcl_and_audio_match": original["returncode"] == 0 and other["returncode"] == 0 and original["streamhash"] == other["streamhash"]}


def validate_and_compare(path, reference):
    probe = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if probe["returncode"] != 0:
        raise ValueError("The transformed original did not parse as a valid media container")
    info = json.loads(probe["stdout"])
    video = [s for s in info["streams"] if s["codec_type"] == "video"]
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not video or not audio:
        raise ValueError("The transformed original lacks a video or audio stream")
    decode = run(["ffmpeg", "-nostdin", "-v", "error", "-err_detect", "explode", "-xerror", "-i", str(path), "-map", "0:v", "-map", "0:a", "-f", "null", "-"])
    if decode["returncode"] != 0:
        raise ValueError("The transformed original failed complete strict audio/video decoding")
    original_hash = streamhash(path)
    reference_hash = streamhash(reference)
    return {"probe": {"returncode": 0, "data": info}, "decode": {"returncode": decode["returncode"], "stderr": decode["stderr"], "all_audio_video_streams": True, "err_detect": "explode"}, "stream_comparison": {"decrypted_original": original_hash, "web_hls_remux": reference_hash, "exact_compressed_streamhash_match": original_hash["returncode"] == 0 and reference_hash["returncode"] == 0 and original_hash["streamhash"] == reference_hash["streamhash"]}, "normalized_stream_comparison": normalized_stream_comparison(path, reference), "video_stream_count": len(video), "audio_stream_count": len(audio), "duration": float(info["format"]["duration"])}


def decrypt_one(item, modulus, exponent, sample_only=False, previous=None):
    lid = str(item["lesson_id"])
    source = ROOT / "assets/video/encrypted" / (lid + ".mp4.enc")
    output = ROOT / "assets/video/decrypted" / (lid + ".mp4")
    source_hash = sha_file(source)
    result = {"lesson_id": lid, "source_path": source.relative_to(ROOT).as_posix(), "source_sha256": source_hash, "source_bytes": source.stat().st_size, "algorithm": "official_v1_rsa_wrapper_and_aes128_custom_counter", "status": "failed"}
    key_bytes = None
    try:
        if not sample_only and output.is_file() and previous and previous.get("status") == "decrypted_verified" and previous.get("source_sha256") == source_hash and previous.get("sha256") == sha_file(output):
            print(f"decrypted {lid}: reused verified output", flush=True)
            return {**previous, "reused_verified_output": True}
        key_bytes, wrapper_info = unpack_token(item["token"], modulus, exponent)
        result["token_structure"] = wrapper_info
        with source.open("rb") as f:
            plain_prefix = transform_blocks(f.read(64), key_bytes)
        result["recovered_mp4_ftyp"] = plain_prefix[4:8] == b"ftyp"
        if not result["recovered_mp4_ftyp"]:
            raise ValueError("The exact native transform did not recover an MP4 ftyp prefix")
        if sample_only:
            result["status"] = "prefix_verified"
            return result
        if output.exists():
            raise ValueError("The dedicated decrypted output already exists; refusing to overwrite")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".part.mp4")
        if temporary.exists():
            raise ValueError("An existing partial decrypted output needs explicit review")
        with source.open("rb") as incoming, temporary.open("xb") as outgoing:
            offset = 0
            while block := incoming.read(1024 * 1024):
                outgoing.write(transform_blocks(block, key_bytes, offset))
                offset += len(block)
        validation = validate_and_compare(temporary, ROOT / "assets/video" / (lid + ".mp4"))
        if sha_file(source) != source_hash:
            raise ValueError("The original file changed during processing")
        temporary.replace(output)
        result.update(validation)
        result.update({"status": "decrypted_verified", "path": output.relative_to(ROOT).as_posix(), "bytes": output.stat().st_size, "sha256": sha_file(output), "original_unchanged": True, "conversion": "exact_native_cipher_transform_without_remux"})
        print(f"decrypted {lid}: verified {result['bytes']:,} bytes", flush=True)
    except Exception as error:
        # Errors are deliberately from our fixed messages, never raw input data.
        result["error_type"] = type(error).__name__
        result["error"] = str(error) if isinstance(error, ValueError) else "Private token processing failed"
        print(f"decrypted {lid}: {result['status']} ({result['error_type']})", flush=True)
    finally:
        key_bytes = None
    return result


def main():
    global ROOT, LIB, REPORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Course archive root; allows this script to be used from a reusable skill")
    parser.add_argument("--library", type=Path, help="Verified official arm64 libddd_ff_protocol.so; defaults under the archive root")
    parser.add_argument("--expected-library-sha256", help="Reject a different native library version before reading its protocol parameters")
    parser.add_argument("--report", type=Path, help="Optional output report path")
    parser.add_argument("--token-input", type=Path, required=True)
    parser.add_argument("--prefix-only", action="store_true")
    parser.add_argument("--lesson-id")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    ROOT = args.root.expanduser().resolve()
    config_path = ROOT / "course-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    protocol = config.get("protocol_library", {})
    default_library = Path(protocol["path"]) if protocol.get("path") else ROOT / "raw/official-player-package/extracted/lib/arm64-v8a/libddd_ff_protocol.so"
    LIB = args.library.expanduser().resolve() if args.library else default_library.expanduser().resolve()
    REPORT = args.report.expanduser().resolve() if args.report else ROOT / "raw/legacy-video-decryption-report.json"
    expected_library_sha256 = args.expected_library_sha256 or protocol.get("sha256")
    if not expected_library_sha256:
        raise ValueError("A verified protocol library SHA-256 is required; use scaffold configuration or --expected-library-sha256")
    if sha_file(LIB) != expected_library_sha256.lower():
        raise ValueError("The official native library version differs from its verified SHA-256")
    if stat.S_IMODE(args.token_input.stat().st_mode) & 0o077:
        raise ValueError("Temporary token input must have owner-only permissions")
    data = json.loads(args.token_input.read_text())
    modulus, exponent, evidence = public_wrapper_parameters()
    # NIST AES known-answer test, using a published synthetic test vector.
    if NativeAES128(bytes.fromhex("000102030405060708090a0b0c0d0e0f")).encrypt_blocks(bytes.fromhex("00112233445566778899aabbccddeeff")) != bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"):
        raise ValueError("AES primitive self-check failed")
    items = [item for item in data["videos"] if not args.lesson_id or str(item["lesson_id"]) == args.lesson_id]
    previous = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    previous_by_id = {v["lesson_id"]: v for v in previous.get("videos", [])}
    results = []
    report = {"schema_version": 1, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "official_algorithm_evidence": evidence, "videos": results, "summary": {}, "keys_or_tokens_saved_in_report": False}
    destination = REPORT.with_name("legacy-video-prefix-report.json") if args.prefix_only else REPORT
    destination.parent.mkdir(parents=True, exist_ok=True)
    def persist():
        report["summary"] = {"requested": len(items), "attempted": len(results), "decrypted_verified": sum(v["status"] == "decrypted_verified" for v in results), "prefix_verified": sum(v["status"] == "prefix_verified" for v in results), "failed": sum(v["status"] == "failed" for v in results)}
        temporary_report = destination.with_suffix(".json.tmp")
        temporary_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_report.replace(destination)
    with ThreadPoolExecutor(max_workers=max(1, min(3, args.workers))) as executor:
        futures = [executor.submit(decrypt_one, item, modulus, exponent, args.prefix_only, previous_by_id.get(str(item["lesson_id"]))) for item in items]
        for future in as_completed(futures):
            results.append(future.result())
            persist()
    order = {str(item["lesson_id"]): i for i, item in enumerate(items)}
    results.sort(key=lambda item: order[item["lesson_id"]])
    persist()
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
