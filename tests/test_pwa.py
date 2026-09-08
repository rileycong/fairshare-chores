import json

import pytest
from django.contrib.staticfiles import finders


@pytest.mark.django_db
class TestManifest:
    def test_manifest_served_at_root_as_json(self, client):
        response = client.get("/manifest.webmanifest")
        assert response.status_code == 200
        assert "manifest" in response.headers["Content-Type"]
        manifest = json.loads(response.content)
        assert manifest["name"] == "FairShare Chores"
        assert manifest["display"] == "standalone"
        assert manifest["theme_color"] == "#2563eb"
        assert manifest["start_url"] == "/"

    def test_manifest_declares_maskable_icons_at_192_and_512(self, client):
        manifest = json.loads(client.get("/manifest.webmanifest").content)
        sizes = {icon["sizes"]: icon for icon in manifest["icons"]}
        assert "192x192" in sizes and "512x512" in sizes
        for icon in sizes.values():
            assert "maskable" in icon["purpose"]
            assert icon["type"] == "image/png"

    @pytest.mark.parametrize("size", [192, 512])
    def test_icon_files_served_as_png(self, client, size):
        response = client.get(f"/icons/icon-{size}.png")
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "image/png"
        assert b"".join(response.streaming_content).startswith(b"\x89PNG")

    @pytest.mark.parametrize("size", [100, 999])
    def test_unsupported_icon_sizes_are_404(self, client, size):
        assert client.get(f"/icons/icon-{size}.png").status_code == 404

    def test_icon_assets_exist_on_disk(self):
        for size in (192, 512):
            path = finders.find(f"icons/icon-{size}.png")
            assert path is not None


@pytest.mark.django_db
class TestServiceWorker:
    def test_service_worker_served_at_root_scope(self, client):
        response = client.get("/service-worker.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["Content-Type"]
        body = response.content.decode()
        assert 'addEventListener("fetch"' in body
        assert 'caches.match("/offline/")' in body
        assert 'addEventListener("install"' in body

    def test_service_worker_registered_on_every_page(self, client):
        for url in ["/", "/offline/"]:
            body = client.get(url).content.decode()
            assert 'navigator.serviceWorker.register("/service-worker.js")' in body

    def test_base_template_links_manifest_and_theme_color(self, client):
        body = client.get("/").content.decode()
        assert 'rel="manifest" href="/manifest.webmanifest"' in body
        assert 'name="theme-color"' in body
        assert 'name="viewport" content="width=device-width, initial-scale=1"' in body


@pytest.mark.django_db
class TestOfflineFallback:
    def test_offline_page_served_and_in_app_shell(self, client):
        response = client.get("/offline/")
        assert response.status_code == 200
        assert "You are offline" in response.content.decode()
        sw = client.get("/service-worker.js").content.decode()
        assert '"/offline/"' in sw
        assert '"/static/css/base.css"' in sw

    def test_no_horizontal_overflow_rules_present(self):
        css_path = finders.find("css/base.css")
        assert css_path is not None
        css = open(css_path).read()
        assert "overflow-x: hidden" in css
        assert "max-width: 30rem" in css
