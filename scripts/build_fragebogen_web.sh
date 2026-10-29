#!/bin/sh
# Builds the public (Vercel) copy of the client questionnaire from the one
# source of truth, backend/static/fragebogen.html. The public copy stores and
# sends nothing: its CSP has connect-src 'none', so the browser itself blocks
# any request carrying answers -- they leave only inside the PDF the client
# shares with the office. Deploy: cd web/fragebogen && npx vercel --prod
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/web/fragebogen"
mkdir -p "$OUT/fragebogen-assets"
cp "$ROOT/backend/static/fragebogen.html" "$OUT/index.html"
cp "$ROOT/backend/static/jspdf.umd.min.js" "$OUT/fragebogen-assets/jspdf.umd.min.js"
cat > "$OUT/vercel.json" <<'JSON'
{
  "cleanUrls": true,
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "Content-Security-Policy", "value": "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'" },
        { "key": "Referrer-Policy", "value": "no-referrer" },
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Robots-Tag", "value": "noindex, nofollow" },
        { "key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()" }
      ]
    }
  ]
}
JSON
# Personal links are private: keep the page out of search engines.
sed -i.bak 's#<meta name="robots" content="index, follow">#<meta name="robots" content="noindex, nofollow">#' "$OUT/index.html" && rm -f "$OUT/index.html.bak"
echo "built $OUT"
