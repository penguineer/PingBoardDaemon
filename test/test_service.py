""" Unit tests for the service module """

import tornado.testing

import json

# noinspection PyUnresolvedReferences
# noinspection PyPackageRequirements
from service import ServiceMgmtEndpoint, GitHealthProvider, HealthHandler


class TestServiceApi(tornado.testing.AsyncHTTPTestCase):

    def get_app(self):
        return ServiceMgmtEndpoint._make_app("src/OAS3.yml")

    def test_health_endpoint_without(self):
        response = self.fetch('/v0/health',
                              method='GET')
        self.assertEqual(200, response.code, "GET /health must be available")

        health = json.loads(response.body.decode())

        assert health['api-version'] == "v0"
        assert "timestamp" in health
        assert "uptime" in health
        assert "git-version" not in health

    def test_health_endpoint_with_git(self):
        git_health_provider = GitHealthProvider()
        HealthHandler.add_health_provider('git-version', git_health_provider.get_health)

        response = self.fetch('/v0/health',
                              method='GET')
        self.assertEqual(200, response.code, "GET /health must be available")

        health = json.loads(response.body.decode())

        self.assertIn('api-version', health, msg="api-version is not provided by health endpoint")
        self.assertEqual("v0", health['api-version'], msg="API version should be v0")
        self.assertIn('git-version', health, msg="git-version is not provided by health endpoint")
        self.assertIn('timestamp', health, msg="timestamp is not provided by health endpoint")
        self.assertIn('uptime', health, msg="uptime is not provided by health endpoint")

    def test_oas3_available(self):
        response = self.fetch('/v0/oas3',
                              method='GET')
        self.assertEqual(200, response.code, "GET /oas3 must be available")

        # check contents against local OAS3.yml
        with open('src/OAS3.yml') as oas3f:
            self.assertEqual(response.body.decode(), oas3f.read(), "OAS3 content differs from spec file!")


class TestServiceApiOas3NotFound(tornado.testing.AsyncHTTPTestCase):

    def get_app(self):
        return ServiceMgmtEndpoint._make_app("OAS3.yml")

    def test_oas3_unavailable(self):
        response = self.fetch('/v0/oas3',
                              method='GET')
        self.assertEqual(404, response.code, "GET /oas3 must be available")
        assert response.body == b"OAS3 specification could not be found!"
