"""Run from project root: python -m unittest discover -s tests"""
import io
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app

class StillroomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)
        cls.root = Path(__file__).resolve().parents[1]

    def test_home_and_health(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertTrue(self.client.get('/api/health').json()['ok'])

    def test_catalog(self):
        result=self.client.get('/api/items')
        self.assertEqual(result.status_code,200)
        self.assertIn('items',result.json())

    def test_invalid_image_rejected(self):
        result=self.client.post('/api/search', files={'image':('bad.jpg',io.BytesIO(b'not an image'),'image/jpeg')})
        self.assertEqual(result.status_code,400)

    def test_demo_visual_search(self):
        file=self.root/'demo'/'reference_2.jpg'
        if not file.exists(): self.skipTest('Generate demo data with python make_demo.py')
        with file.open('rb') as f:
            response=self.client.post('/api/search',files={'image':('query.jpg',f,'image/jpeg')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['results'][0]['item']['name'],'Network handbook')

    def test_demo_scene_scan(self):
        file=self.root/'demo'/'sample_scene.jpg'
        if not file.exists(): self.skipTest('Generate demo data with python make_demo.py')
        with file.open('rb') as f:
            response=self.client.post('/api/scan',files={'image':('scene.jpg',f,'image/jpeg')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['found']),3)

if __name__=='__main__':unittest.main()
