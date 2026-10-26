#!/usr/bin/env python3
"""Synthetic pixel/animation integrity and fresh-vs-incremental image checks."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'assets/dedao-template/scripts'))
from verify_images import png_structure,run_validation

def chunk(kind,data,bad=False):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',0 if bad else zlib.crc32(kind+data)&0xffffffff)
def png(ancillary=False,broken=False):
    parts=[chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))]
    if ancillary:parts.append(chunk(b'stAg',b'Synthetic metadata',True))
    parts += [chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00'),broken),chunk(b'IEND',b'')]
    return b'\x89PNG\r\n\x1a\n'+b''.join(parts)

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required by archive media workflow')
class ImageVerificationTests(unittest.TestCase):
    def test_full_pixel_decode_and_resume_scope(self):
        with tempfile.TemporaryDirectory(prefix='skill-image-fixture-') as directory:
            root=Path(directory);images=root/'assets/images';images.mkdir(parents=True)
            (images/'one.png').write_bytes(png());(images/'same.png').write_bytes(png())
            first=run_validation(root,fresh=True,audit_run_id='first',timeout=15)
            self.assertEqual(first['status'],'passed');self.assertEqual(first['summary']['fresh_unique_decodes'],1)
            self.assertTrue(all(row['frames_decoded']==1 and row['all_frames_decoded'] for row in first['images']))
            same=run_validation(root,fresh=True,audit_run_id='first',resume_same_run=True,timeout=15)
            self.assertEqual(same['summary']['reused_unique_decodes'],1)
            other=run_validation(root,fresh=True,audit_run_id='second',resume_same_run=True,timeout=15)
            self.assertEqual(other['summary']['fresh_unique_decodes'],1);self.assertEqual(other['summary']['reused_unique_decodes'],0)

    def test_source_ancillary_warning_preserves_pixels_and_original(self):
        with tempfile.TemporaryDirectory(prefix='skill-image-warning-') as directory:
            root=Path(directory);image=root/'assets/images/warning.png';image.parent.mkdir(parents=True)
            value=png(ancillary=True);image.write_bytes(value)
            report=run_validation(root,fresh=True,timeout=15)
            self.assertEqual(report['status'],'passed_with_source_warnings')
            self.assertEqual(report['images'][0]['full_decode_exit_code'],0)
            self.assertEqual(image.read_bytes(),value)
            image.write_bytes(png(broken=True))
            report=run_validation(root,fresh=True,timeout=15)
            self.assertEqual(report['status'],'failed');self.assertIn('Critical PNG',report['images'][0]['error'])

    def test_all_animation_frames_are_decoded(self):
        with tempfile.TemporaryDirectory(prefix='skill-image-animation-') as directory:
            root=Path(directory);image=root/'assets/images/animation.gif';image.parent.mkdir(parents=True)
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc=size=16x16:rate=2','-t','1','-y',str(image)],check=True,capture_output=True,timeout=15)
            report=run_validation(root,fresh=True,timeout=15)
            self.assertEqual(report['status'],'passed');self.assertEqual(report['images'][0]['frames_decoded'],2)

if __name__=='__main__':unittest.main()
