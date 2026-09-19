"""Index captured DOM files offline; never fetch URLs or submit forms.

Run with the repository virtualenv: python build_inventory.py CAPTURE_DIR.
The output is structural metadata, not sanitized HTML or reusable JSF payloads.
"""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def clean_url(value, base="https://sigaa.ufcg.edu.br/", private=False):
    url = urlsplit(urljoin(base, value))
    path = re.sub(r";jsessionid=[^/?#;]*", "", url.path, flags=re.I) or "/"
    # Keep only public navigation parameters; never export session/download keys.
    query = [(k, v) for k, v in parse_qsl(url.query)
             if not private and k in {"aba", "nivel", "acao", "lc", "id", "siape", "noticia",
                      "acessibilidade", "idProducao", "idArquivo"}]
    return urlunsplit((url.scheme, url.netloc, path, urlencode(sorted(query)), ""))


def summarize(entry, html):
    private = entry.get("access") == "authenticated"
    soup = BeautifulSoup(html, "lxml")
    visible_text = soup.get_text(" ", strip=True)
    headings = [e.get_text(" ", strip=True) for e in soup.select("h1,h2,h3,caption")]
    status = "captured_dom"
    if "Comportamento Inesperado!" in headings:
        status = "server_error_render"
    elif soup.select_one('form[name="loginForm"]'):
        status = "login_form"
    if entry["id"] == "067-component-program":
        status = "action_destination_unverified"
    complete_html = html.rstrip().lower().endswith("</html>")
    if not complete_html:
        status = "incomplete_html"
    forms = []
    for form in soup.select("form"):
        forms.append({
            "id": form.get("id"), "name": form.get("name"),
            "method_declared": form.get("method", "get").upper(),
            "action": clean_url(form.get("action", ""), entry["url"], private),
            "controls": [{"tag": e.name, "type": e.get("type"),
                          "name": e.get("name"), "id": e.get("id")}
                         for e in form.select("input,select,textarea,button")],
        })
    links = []
    for a in soup.select("a"):
        href, onclick = a.get("href", ""), a.get("onclick", "")
        kind = "jsf_postback" if "jsfcljs" in onclick else "script_or_fragment"
        url = None
        if href and not href.startswith(("#", "javascript:", "mailto:")):
            url = clean_url(href, entry["url"], private)
            kind = "internal_url" if urlsplit(url).hostname == "sigaa.ufcg.edu.br" else "external_url"
            if private and kind == "external_url":
                url = None  # Private document identifiers can occur in URL paths too.
        label = " ".join(a.get_text(" ", strip=True).split()) or a.get("title", "")
        links.append({"label": "" if private else label, "kind": kind, "url": url,
                      "query_field_names": sorted({k for k, _ in parse_qsl(urlsplit(href).query)}),
                      "jsf_field_names": re.findall(r"'([^']+)'\s*:", onclick)})
    return {
        **entry, "title": "Authenticated page" if private else entry.get("title"),
        "url": clean_url(entry["url"], private=private),
        "requested_url": clean_url(entry["requested_url"], private=private) if entry.get("requested_url") else None,
        "status": status, "complete_html": complete_html,
        "size_bytes": len(html.encode("utf-8")), "headings": [] if private else headings,
        "captcha_marker_present": bool(re.search(r"captcha|conteúdo da imagem", html, re.I)),
        "has_password_field": bool(soup.select_one('input[type="password"]')),
        "empty_state_messages": [] if private else sorted(set(re.findall(
            r"(?:Nenhum[a]?|Não há)[^.\n<>]{0,160}", visible_text))),
        "forms": forms, "links": links,
        "tables": [{"id": t.get("id"), "classes": t.get("class", []),
                    "row_count": len(t.select("tr"))} for t in soup.select("table")],
    }


def build(root):
    manifest = json.loads((root / "manifest.json").read_text())
    assert len({e["id"] for e in manifest}) == len(manifest), "Duplicate capture ID"
    pages = []
    for entry in manifest:
        path = root / entry["file"]
        assert path.resolve().parent == root.resolve(), "Capture outside input directory"
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["id"]
        pages.append(summarize(entry, data.decode("utf-8")))
    visited = {page["url"] for page in pages if page["complete_html"]}
    requested = {page["requested_url"] for page in pages
                 if page["requested_url"] and page["complete_html"]}
    frontier = {}
    for page in pages:
        for link in page["links"]:
            if link["url"] and link["url"] not in visited | requested:
                key = link["url"]
                frontier.setdefault(key, {"url": key, "kind": link["kind"],
                                          "sources": [], "status": "not_captured"})
                if page["id"] not in frontier[key]["sources"]:
                    frontier[key]["sources"].append(page["id"])
    result = {
        "schema_version": 1, "host": "sigaa.ufcg.edu.br", "complete": False,
        "scope": "Public and authenticated rendered DOM; full recursive coverage pending",
        "capture_directory": "captures/sigaa-ufcg/2026-09-18",
        "limitations": ["Not raw HTTP response bodies; no response headers or status codes",
                        "Form methods are declarations, not a network trace",
                        "No field values, cookies, passwords or ViewState values exported",
                        "Authenticated titles, headings, link labels, external URLs and query values omitted",
                        "Incomplete HTML is flagged and must be recaptured before compatibility conclusions",
                        "Frontier covers href URLs only; JSF actions remain listed per page",
                        "Unvisited URLs are not evidence that an endpoint works"],
        "counts": {"captures": len(pages), "distinct_urls": len({p['url'] for p in pages}),
                   "complete_html": sum(p["complete_html"] for p in pages),
                   "access": dict(Counter(p.get("access", "public") for p in pages)),
                   "statuses": dict(Counter(p["status"] for p in pages)),
                   "frontier_urls": len(frontier)},
        "pages": pages, "frontier": sorted(frontier.values(), key=lambda e: e["url"]),
    }
    out = Path(__file__).parent
    (out / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    rows = ["# Índice das capturas UFCG", "", "Gerado offline; `captured_dom` não significa funcionalidade testada.",
            "HTMLs são locais e ignorados pelo Git. `incomplete_html` exige recaptura; URL igual pode representar estados diferentes.",
            "", "| Captura | Origem / ação | Estado | HTML local |", "| --- | --- | --- | --- |"]
    for page in pages:
        source = page["source"].replace("|", "\\|").replace("\n", " ")
        rows.append(f'| {page["id"]} | {source} | {page["status"]} | '
                    f'[HTML](../../captures/sigaa-ufcg/2026-09-18/{page["file"]}) |')
    (out / "captures.md").write_text("\n".join(rows) + "\n")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    # One runnable check: secret stripping, JSF state distinction, error detection.
    assert clean_url("/x;jsessionid=SECRET?id=42&key=SECRET#top").endswith("/x?id=42")
    sample = summarize({"id": "self-test", "url": "https://sigaa.ufcg.edu.br/x"},
                       '<h3>Comportamento Inesperado!</h3><form method="post">'
                       '<input name="javax.faces.ViewState" value="SECRET"></form></html>')
    assert sample["status"] == "server_error_render" and "SECRET" not in json.dumps(sample)
    assert sample["forms"][0]["method_declared"] == "POST"
    private_sample = summarize({"id": "private-test", "access": "authenticated",
                                "title": "SECRET", "url": "https://sigaa.ufcg.edu.br/x?id=SECRET"},
                               '<h1>SECRET</h1><a href="/x?id=SECRET">SECRET</a>')
    assert "SECRET" not in json.dumps(private_sample)
    assert private_sample["status"] == "incomplete_html"
    assert summarize({"id": "cut", "url": "https://sigaa.ufcg.edu.br/"},
                     '<html>[Truncated]')["status"] == "incomplete_html"
    if sys.argv[1:] != ["--self-test"]:
        build(Path(sys.argv[1]))
