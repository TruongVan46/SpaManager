import unittest
import os

# Set environment variable to testing to load TestingConfig
os.environ["APP_ENV"] = "testing"

from app import app

class BasicTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_app_initialization(self):
        """Test that the flask app initialized successfully."""
        self.assertIsNotNone(app)

    def test_login_page_loads(self):
        """Test that the login page loads successfully."""
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
