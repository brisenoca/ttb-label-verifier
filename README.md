# TTB Label Verification

A prototype that checks alcohol beverage label artwork against the data declared
on its COLA application, and tells a compliance agent which fields agree and
which do not.

**Live demo:** _(add your deployed URL here)_

---

## What it does

Upload one label image, or several hundred, along with the application records
they belong to. For each label the application:

1. reads the printed fields off the artwork with a vision model,
2. compares each field against the application using deterministic rules,
3. returns a per-field verdict with the reasoning behind it.

Every field lands in one of three states. **Match** and **Mismatch** mean the
rules were conclusive. **Review** means they were not, and a human should look —
which is a deliberate design decision, not a hedge. See
[ASSUMPTIONS.md](ASSUMPTIONS.md).

---

## Running it

Requires Python 3.11 or newer.

Dependencies are specified as minimum versions rather than exact pins, so `pip`
selects builds matching your Python rather than trying to compile from source.

```bash
git clone <your-repo-url>
cd ttb-label-verifier

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python samples/generate_labels.py                    # writes 10 test labels
uvicorn app.main:app --reload
```

Open <http://localhost:8000>.

It runs immediately with no API key, using a built-in offline extractor so you
can exercise the full interface and every comparison path. For live extraction
from real images:

Copy `.env.example` to `.env`, paste your key into it, and restart:

```bash
cp .env.example .env        # Windows: copy .env.example .env
# edit .env, set ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload
```

`.env` is gitignored and is never committed. Real environment variables take
precedence over it, which is what deployment platforms set.

The footer of the page always states which extractor is active.

### Trying it

Choose **Several labels**, select everything in `samples/labels/`, click **Load
sample records**, then **Verify labels**. The ten test images are each built to
trigger one specific rule — the filenames say which.

### Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

35 tests, all offline. They cover the comparison rules, which are the part of
the system that decides whether a label passes.

### With Docker

```bash
docker build -t ttb-label-verification .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... ttb-label-verification
```

---

## How it works

```
  image ──▶ preprocess ──▶ vision extraction ──▶ rules comparison ──▶ result
            (rotate,        (structured           (deterministic,      (per-field
             downscale,      transcription        no model in the       verdict +
             re-encode)      via tool call)        loop)                reasoning)
```

**Extraction is the only place a model is used, and it only transcribes.** It is
told what is printed, not whether the label is compliant. It never fills a gap:
a field it cannot read comes back as `null`, which the comparison stage reports
as absent rather than treating as a match.

**Comparison is entirely deterministic.** Three reasons: an applicant whose label
is rejected is entitled to know which rule rejected it; the rules can be unit
tested, and a model's judgment cannot be pinned down the same way; and it costs
nothing and takes about a millisecond, which is most of the five second budget
handed straight back.

The two stages meet at `ExtractedLabel` in `app/schemas.py`. Nothing else
crosses between them.

### The two matching strategies

The interviews describe two problems that pull in opposite directions, so the
application uses different rules for each.

**Most fields tolerate variation.** Dave Morrison's example — `STONE'S THROW`
on the label, `Stone's Throw` on the form — is the same product, and flagging it
wastes an agent's time. These fields run a ladder from strictest to loosest:
exact, then exact-after-normalization, then fuzzy. Fuzzy scoring combines
character similarity with token similarity and takes the more pessimistic of the
two, because character similarity alone rates `OLD TOM DISTILLERY` and
`NEW TOM DISTILLERY` as 89% alike. The reported verdict always names the
strongest rule that fired, so the interface can say *"only capitalization
differs"* rather than just *"match."*

**The government warning tolerates nothing.** 27 CFR 16.21 prescribes the exact
wording and 16.22 requires `GOVERNMENT WARNING` in capitals. Jenny Park rejected
a label for title-casing that prefix, so the software applies the same rule:
character-for-character, case-sensitive, with only line breaks normalized away.
When it fails, the result names the specific altered wording rather than just
reporting a failure.

Alcohol content and net contents are compared numerically, not textually.
`0.75 L` and `750 mL` are the same volume; `90 Proof` and `45% Alc./Vol.` are
the same strength. Alcohol tolerance varies by beverage type.

### Meeting the five second target

Sarah Chen was explicit that the previous vendor pilot died at 30–40 seconds per
label. Four things keep this well inside the budget:

- Oversized images are downscaled before upload, which cuts both transfer time
  and the model's image token count. Measurement changed this rule: re-encoding
  everything to JPEG *inflated* flat artwork stored as PNG, so re-encoding now
  happens only when it actually produces a smaller file.
- The default model is Claude Haiku 4.5, chosen for latency. Transcription is
  well within its capability, so a larger model buys accuracy the task does not
  need.
- Batches fan out concurrently rather than looping, bounded by a semaphore.
- Comparison never touches the network.

Measured time is shown in the interface for every label, split into reading and
comparing, and the summary turns red past five seconds. The number is not
claimed, it is displayed.

### The interface

Sarah's benchmark was her 73-year-old mother and half her team is over 50, so:
17px base text, 48px minimum control height, one column, one path down the page,
and no interaction that depends on hover or on noticing something small.

Verdicts never rely on color alone — each pairs a color with a glyph and a word,
which is a Section 508 requirement and also the only way the distinction survives
a printed page or a colorblind reader.

Marcus Williams mentioned the firewall blocks outbound domains, so there are no
webfonts, no icon library and no CDN. There is also no build step: the page is
HTML, CSS and one JavaScript file. A reviewer needs `uvicorn` and nothing else.

---

## Layout

```
app/
  main.py                     HTTP endpoints, batch fan-out, timing
  config.py                   environment configuration, extractor selection
  schemas.py                  the data contract between stages
  extraction/
    base.py                   VisionExtractor interface, image preprocessing
    anthropic_extractor.py    Claude implementation, structured via tool call
    mock_extractor.py         offline extractor for tests and demos
  comparison/
    normalize.py              typography and whitespace folding
    matchers.py               text, alcohol content and net contents rules
    warning.py                government warning exact-match rule
    engine.py                 assembles field checks into one verdict
  static/                     the interface
tests/                        35 offline tests of the comparison rules
samples/
  generate_labels.py          renders the 10 test labels
  applications.json           matching COLA records
```

Extraction sits behind a one-method interface. Marcus's firewall story — the
vendor pilot where half the features died because outbound ML endpoints were
blocked — is a real risk for this design, so swapping to a different provider, a
model hosted inside the FedRAMP boundary, or something local is a new file in
`app/extraction/` rather than a rewrite.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/verify` | One image plus one application record |
| `POST /api/verify-batch` | Many images plus a JSON array of records, matched by filename |
| `GET /api/health` | Status and active extractor |
| `GET /api/sample-applications` | Sample COLA records |

Interactive docs at `/docs`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | _(unset)_ | Unset runs the offline extractor |
| `EXTRACTION_MODEL` | `claude-haiku-4-5-20251001` | Override to trade cost for accuracy |
| `EXTRACTION_TIMEOUT_S` | `20` | Per-label extraction timeout |
| `MAX_BATCH_SIZE` | `50` | Labels per batch request |
| `MAX_CONCURRENCY` | `8` | Concurrent extractions |

## Deploying

`render.yaml` and the `Dockerfile` are included. Point Render at the repository,
set `ANTHROPIC_API_KEY` in the dashboard, and it builds from the Dockerfile.

Note that free tiers on Render and similar services idle out after inactivity, so
the first request after a quiet period pays a cold start of roughly a minute.
That is container startup, not label processing — the per-label timing shown in
the interface is measured server-side and excludes it.

---

## Development notes

This prototype was built with AI assistance (Claude), which is disclosed here
deliberately rather than left implicit.

The architectural decisions were made before implementation and drove it:
rules-based comparison rather than model judgment for the compare step, chosen
for explainability in a compliance context; the four-stage pipeline; the
sub-five-second latency target taken from the stakeholder interviews; and the
extraction layer kept behind an interface in response to the firewall constraint
Marcus Williams described. Claude was used to implement those decisions, to write
the test suite, and to draft this documentation.

One decision came out of the implementation rather than preceding it. The initial
fuzzy matcher used character similarity alone, and a test caught it rating
`OLD TOM DISTILLERY` and `NEW TOM DISTILLERY` as 89% alike — a passing score for
two different products. The matcher now combines character and token similarity
and takes the more pessimistic of the two.

## Known limitations

Written up in full in [ASSUMPTIONS.md](ASSUMPTIONS.md). The short version:

- Front label only. Multi-panel artwork, back labels and wraparounds are not handled.
- No type size or contrast measurement. 27 CFR 16.22 sets minimum type sizes for
  the warning; that needs physical dimensions the artwork does not carry.
- English only.
- The regulatory constants — warning text, alcohol tolerances — are configuration
  in the code and are cited to the CFR, but they must be verified against the
  current regulation before any real use.
- Nothing is persisted. No database, no file retention, no audit log. A real
  deployment needs all three.
