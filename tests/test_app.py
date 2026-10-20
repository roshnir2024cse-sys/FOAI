import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E  # noqa: E402
from app import create_app  # noqa: E402


def payload():
    apps = []
    for s in E.SAMPLE_HOME:
        p = dict(E.PRESET_BY_KEY[s["key"]])
        p.update(s)
        apps.append(p)
    return {"appliances": apps, "settings": {"tariff_mode": "flat", "tariff_rate": 8, "comfort_target": 80}}


class AppTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"DATABASE": self.path, "TESTING": True, "SEED_DEMO": True})
        self.c = self.app.test_client()

    def tearDown(self):
        os.unlink(self.path)

    def token(self, url="/login"):
        html = self.c.get(url).get_data(as_text=True)
        return re.search(r'name="csrf" content="([^"]+)"', html).group(1)

    def login(self, email="demo@ecowise.ai", pw="Demo@1234"):
        t = self.token()
        return self.c.post("/login", data={"email": email, "password": pw, "csrf_token": t})

    def test_pages_require_login(self):
        for url in ("/dashboard", "/history", "/settings"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login", r.headers["Location"])
        self.assertEqual(self.c.post("/api/optimize", json=payload()).status_code, 400)  # CSRF first

    def test_login_logout(self):
        self.assertEqual(self.login("demo@ecowise.ai", "wrong").status_code, 200)
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/dashboard").status_code, 200)
        t = self.token("/dashboard")
        self.c.post("/logout", data={"csrf_token": t})
        self.assertEqual(self.c.get("/dashboard").status_code, 302)

    def test_post_without_csrf_rejected(self):
        r = self.c.post("/login", data={"email": "demo@ecowise.ai", "password": "Demo@1234"})
        self.assertEqual(r.status_code, 400)

    def test_open_redirect_blocked(self):
        t = self.token()
        r = self.c.post("/login?next=https://evil.example", data={"email": "demo@ecowise.ai", "password": "Demo@1234", "csrf_token": t})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil", r.headers["Location"])

    def test_register_validation_and_success(self):
        t = self.token("/register")
        bad = self.c.post("/register", data={"name": "A", "email": "x", "password": "abc", "confirm": "abc", "csrf_token": t})
        self.assertEqual(bad.status_code, 200)
        ok = self.c.post("/register", data={"name": "Roshni R", "email": "r@example.com", "password": "Passw0rd!", "confirm": "Passw0rd!", "csrf_token": t})
        self.assertEqual(ok.status_code, 302)
        # sign out, then try to register the same email again
        self.c.post("/logout", data={"csrf_token": self.token("/dashboard")})
        t2 = self.token("/register")
        dup = self.c.post("/register", data={"name": "Roshni R", "email": "r@example.com", "password": "Passw0rd!", "confirm": "Passw0rd!", "csrf_token": t2})
        self.assertEqual(dup.status_code, 200)
        self.assertIn("already exists", dup.get_data(as_text=True))

    def test_api_flow(self):
        self.login()
        t = self.token("/dashboard")
        h = {"X-CSRF-Token": t}
        r = self.c.post("/api/optimize", json=payload(), headers=h)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["optimization"]["feasible"])
        # invalid input
        bad = payload()
        bad["appliances"][0]["hours"] = 99
        self.assertEqual(self.c.post("/api/optimize", json=bad, headers=h).status_code, 400)
        # what-if
        body = payload()
        body["hours"] = [a["hours"] / 2 for a in body["appliances"]]
        w = self.c.post("/api/calculate", json=body, headers=h)
        self.assertEqual(w.status_code, 200)
        self.assertGreater(w.get_json()["monthly_saved"], 0)
        # save / load / delete
        s = self.c.post("/api/history", json=dict(payload(), title="Test"), headers=h)
        self.assertEqual(s.status_code, 201)
        aid = s.get_json()["id"]
        self.assertIn("Test", self.c.get("/history").get_data(as_text=True))
        g = self.c.get(f"/api/history/{aid}")
        self.assertEqual(g.status_code, 200)
        self.assertEqual(g.get_json()["settings"]["comfort_target"], 80)
        self.assertEqual(self.c.delete(f"/api/history/{aid}", headers=h).status_code, 200)
        self.assertEqual(self.c.get(f"/api/history/{aid}").status_code, 404)

    def test_users_cannot_see_each_others_history(self):
        self.login()
        h = {"X-CSRF-Token": self.token("/dashboard")}
        aid = self.c.post("/api/history", json=payload(), headers=h).get_json()["id"]
        self.c.post("/logout", data={"csrf_token": h["X-CSRF-Token"]})
        t = self.token("/register")
        self.c.post("/register", data={"name": "Other", "email": "o@example.com", "password": "Passw0rd!", "confirm": "Passw0rd!", "csrf_token": t})
        self.assertEqual(self.c.get(f"/api/history/{aid}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
