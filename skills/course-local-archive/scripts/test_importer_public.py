#!/usr/bin/env python3
"""Small synthetic offline regressions for source rendering and catalog paging."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

TEMPLATE = Path(__file__).resolve().parents[1]/'assets/dedao-template/scripts'
sys.path.insert(0,str(TEMPLATE))
import import_authorized as importer
from fetch_public_catalog import collect_catalog
from image_assets import metadata_html_images, metadata_sections, localize_html_images

def text(value): return {'type':'text','text':{'content':value}}
def row(number, **extra): return {'id':number,'enid':'SyntheticArticle'+str(number),'title':'Synthetic '+str(number),'order_num':number,**extra}

class CatalogTests(unittest.TestCase):
    def reader(self,pages,sections=None,count=3):
        calls=[]
        def read(path,payload):
            calls.append((path,payload.copy()))
            if path.endswith('/class/info'):
                return {'h':{'c':0},'c':{'class_info':{'enid':'SyntheticCourse','current_article_count':count},'chapter_list':sections or []}}
            index=len([c for c in calls if c[0].endswith('/free_article_list')])-1
            return {'h':{'c':0},'c':pages[min(index,len(pages)-1)]}
        return read,calls

    def test_flat_course_and_real_pagination(self):
        reader,calls=self.reader([{'article_list':[row(1),row(2)],'has_more':'1'}, {'article_list':[row(3)],'has_more':'0'}])
        _,catalog,pages=collect_catalog('SyntheticCourse',reader,delay=0)
        self.assertEqual([r['id'] for r in catalog['chapter_list'][0]['article_list']],[1,2,3])
        self.assertEqual(calls[1][1]['chapter_id'],'0')
        self.assertEqual(calls[2][1]['max_id'],'2')
        self.assertEqual(len(pages),2)

    def test_full_unpaged_section_no_unneeded_next_page(self):
        reader,calls=self.reader([{'article_list':[row(1),row(2),row(3)]}],[{'id':'one','name':'Synthetic section'}])
        _,catalog,_=collect_catalog('SyntheticCourse',reader,delay=0)
        self.assertEqual(len(catalog['chapter_list'][0]['article_list']),3)
        self.assertEqual(len(calls),2)

    def test_truncated_catalog_fails(self):
        reader,_=self.reader([{'article_list':[row(1)],'has_more':False}])
        with self.assertRaisesRegex(ValueError,'incomplete'):collect_catalog('SyntheticCourse',reader,delay=0)

    def test_repeated_page_cannot_claim_more(self):
        reader,_=self.reader([{'article_list':[row(1)],'has_more':True}])
        with self.assertRaisesRegex(ValueError,'did not advance'):collect_catalog('SyntheticCourse',reader,delay=0)

    def test_duplicate_article_enid_refused(self):
        reader,_=self.reader([{'article_list':[row(1),row(2,enid='SyntheticArticle1')],'has_more':False}],count=2)
        with self.assertRaisesRegex(ValueError,'duplicate article enids'):collect_catalog('SyntheticCourse',reader,delay=0)

class RenderTests(unittest.TestCase):
    def renderer(self):
        lesson={'id':'SyntheticLesson','info':{'article_info':{'video':[{'dd_media_id_str':'SyntheticVideo'}]}}}
        return importer.Renderer(lesson,{})

    def test_quote_author_is_preserved_even_when_plain_text_omits_it(self):
        r=self.renderer();markup,expected=r.block({'type':'blockquote','subtype':1,'cite':{'author':{'name':'Synthetic Author'}},'contents':[text('Quoted sentence.')],'text':'Quoted sentence.'},0)
        self.assertIn('Synthetic Author',markup);self.assertIn('Quoted sentence.',markup)
        self.assertEqual(expected,'Synthetic AuthorQuoted sentence.')
        self.assertEqual(r.issues,[])

    def test_product_fields_preserved(self):
        r=self.renderer();markup,expected=r.block({'type':'product-item','id':'SyntheticProduct','info':{'title':'Title','des':'Description','price':'12.50'}},0)
        self.assertEqual(expected,'TitleDescription12.50')
        for value in ('Title','Description','12.50'):self.assertIn(value,markup)
        self.assertEqual(r.issues,[])

    def test_empty_source_vote_is_recorded_without_invented_content(self):
        r=self.renderer();markup,expected=r.block({'type':'vote'},0)
        self.assertEqual(expected,'');self.assertIn('not-provided',markup)
        self.assertEqual([i['kind'] for i in r.issues],['source_interaction_marker_only'])
        other=self.renderer();other.block({'type':'vote','question':'Unrecognized nonempty source interaction'},0)
        self.assertTrue(any(i['kind']=='unsupported_block' for i in other.issues))

    def test_video_requires_exact_declared_source_identity(self):
        r=self.renderer();markup,expected=r.block({'type':'video','mediaId':'SyntheticVideo','title':'Clip title'},0)
        self.assertIn('SyntheticVideo',markup);self.assertEqual(expected,'Clip title');self.assertEqual(r.issues,[])
        bad=self.renderer();bad.block({'type':'video','mediaId':'DifferentVideo','title':'Clip title'},0)
        self.assertTrue(any(i['kind']=='embedded_video_source_not_mapped' for i in bad.issues))

    def test_new_metadata_image_variants(self):
        metadata={key:'https://example.invalid/'+key+'.jpg' for key in ('index_img_applet','special_logo','logo_for_lecture')}
        self.assertEqual({key for _,key in importer.image_locations(metadata)},set(metadata))
        self.assertEqual(list(importer.image_locations({'url':'https://example.invalid/citation'})),[])

    def test_course_metadata_images_are_scoped_and_localized(self):
        content='<p>A &amp; B<img src="https://example.invalid/pic?a=1&amp;b=2" alt="exact"></p>'
        metadata={'items':[{'title':'Intro','content':content}], 'new_items':[{'title':'Intro','content':content}], 'reviews':[{'content':'<img src="https://example.invalid/avatar">'}]}
        self.assertEqual(list(metadata_html_images(metadata)),['https://example.invalid/pic?a=1&b=2'])
        self.assertEqual(len(list(metadata_sections(metadata))),1)
        result=localize_html_images(content,{'https://example.invalid/pic?a=1&b=2':{'path':'assets/images/pic.png'}})
        self.assertEqual(result,'<p>A &amp; B<img src="../assets/images/pic.png" alt="exact"></p>')
        self.assertEqual(content,metadata['items'][0]['content'])
        with self.assertRaisesRegex(ValueError,'no local copy'):localize_html_images(content,{})

    def test_bmp_original_bytes_survive_octet_stream_response(self):
        # One real 1x1 24-bit BMP, padded to its required four-byte pixel row.
        dib=struct.pack('<IIIHHIIIIII',40,1,1,1,24,0,4,2835,2835,0,0)
        body=b'BM'+struct.pack('<IHHI',58,0,0,54)+dib+b'\x00\x00\xff\x00'
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return body
        with tempfile.TemporaryDirectory(prefix='course-importer-fixture-') as directory:
            old=importer.ROOT;importer.ROOT=Path(directory)
            try:
                with patch.object(importer.urllib.request,'urlopen',return_value=Response()):
                    saved=importer.download_image('https://example.invalid/synthetic.bmp',None)
                self.assertTrue(saved['path'].endswith('.bmp'))
                self.assertEqual((Path(directory)/saved['path']).read_bytes(),body)
            finally:importer.ROOT=old

if __name__=='__main__':unittest.main()
