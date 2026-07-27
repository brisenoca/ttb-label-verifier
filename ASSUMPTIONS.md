# Assumptions, trade-offs and limitations

The brief said it valued how gaps get filled independently, so this records what
was assumed, what was decided against, and what is missing.

---

## Assumptions

**Application data arrives as structured fields.** The prototype takes them from
a form or a JSON array rather than parsing a COLA submission. Marcus Williams was
clear that COLA integration is out of scope, and in the real system these fields
are already structured — they were typed into a form by the applicant.

**Front label artwork, one image per application.** Real submissions include
multiple panels. Extending to multi-panel means extracting each panel and merging
before comparison; the interface is unchanged, the comparison stage is unchanged,
and only the extractor's input shape moves. It was left out to keep the core
pipeline complete rather than have every stage half-built.

**Distilled spirits are the default beverage type.** The sample label is a
bourbon and the type is selectable. It matters because the permitted alcohol
tolerance differs by type.

**The regulatory constants are correct as of writing but are configuration, not
truth.** The warning text is 27 CFR 16.21 and the tolerances reflect the commonly
cited figures in 27 CFR Parts 4, 5 and 7. They sit in named constants with
citations, one per rule, so a regulatory amendment is a one-line change and a
matching test. They should be verified against the current CFR before any real
use. This is worth flagging specifically: there has been active policy discussion
about the alcohol warning statement, and a prototype that hard-codes a superseded
statement would fail every label it saw.

---

## Trade-offs

### Rules for comparison, not model judgment

The most consequential decision here. The model could have been handed both the
label and the application and asked whether they agree. It was not.

**Why rules.** An applicant whose label is rejected is entitled to know which
rule rejected it, and *"the wording deviates from 27 CFR 16.21 at this phrase"*
is an answer while *"the model assessed it as non-compliant"* is not. Rules can
also be unit tested — the 35 tests here pin the behavior of every rule, and no
equivalent test exists for a model's judgment. And rules cost nothing and take
about a millisecond, which is budget handed back to the part that needs it.

**What it costs.** The rules cannot exercise the judgment Dave Morrison
described. They handle his specific example correctly, but a case they have not
anticipated gets a mechanical answer rather than a sensible one.

**How that cost is contained.** By the three-state verdict. A binary pass/fail
would force the rules to resolve every ambiguity, and they are not qualified to.
**Review** is where the system says it does not know, and routes to the person
who does. The verdicts are also deliberately named *Match*, *Review* and
*Mismatch* rather than *Approved* and *Rejected* — the tool reports agreement
between two documents, it does not make a compliance determination.

### Extraction behind an interface

Marcus Williams raised this twice: outbound traffic to many domains is blocked,
and a previous vendor pilot lost half its features because the firewall blocked
their ML endpoints. It is the sharpest technical constraint in the brief and it
deserves a direct answer.

**The prototype does call a cloud API, deliberately.** Marcus scoped his own
remark — COLA integration is out, this is a standalone proof-of-concept, and
"for a prototype, just don't do anything crazy." The deployed demo runs on public
infrastructure rather than inside TTB's network, so the firewall does not apply
to it. Removing the vision model to satisfy a production constraint would have
cost the capability the assignment is named for, including the one judgment that
genuinely needs vision: whether `GOVERNMENT WARNING` is *rendered* in capitals,
which is a property of the artwork rather than of the text.

**What the constraint changed is the architecture, not the capability.**
Extraction is one abstract method, `VisionExtractor.extract`. No vendor SDK is
imported anywhere else in the codebase, and nothing outside `app/extraction/`
knows a network exists. Two implementations ship, which is the point: the
interface is exercised, not theoretical.

Three migration paths follow from that, in increasing order of effort:

1. **A model inside the existing boundary.** TTB is already on Azure. Claude
   models are available through Microsoft Foundry and AWS Bedrock, so the same
   model can be reached from inside a tenant that never egresses to the public
   internet. This is a change of client construction, not of logic — realistically
   an afternoon.
2. **A different provider.** A new file in `app/extraction/`, roughly 60 lines.
3. **A local model.** Same interface, higher infrastructure cost, and a quality
   trade-off that would need measuring before anyone committed to it.

The comparison rules are unaffected by all three. They never touch the network,
and they are where the compliance decisions actually happen.

The offline extractor exists for this reason as much as for testing: an
application that can demonstrate nothing without an outbound connection is hard
to evaluate in exactly the environment Marcus described.

### Structured output via tool call, not JSON parsing

The model is required to call a tool whose schema is the extraction contract, so
the response arrives already conforming. There is no brace matching, no markdown
fence stripping, and no parse-failure path anywhere in the codebase.

### Haiku over a larger model

Transcription is well within Haiku 4.5's vision capability, and its latency is
what makes five seconds comfortable rather than tight. `EXTRACTION_MODEL`
overrides it. A production version would plausibly escalate to a larger model
when the extractor reports poor legibility — worth building, not built.

### No framework, no build step

One page with three states does not justify a bundler, and a prototype a
reviewer can run with `uvicorn` alone is worth more than one that needs `npm
install` first.

### No database

Nothing is persisted, in line with Marcus's note that nothing sensitive should be
stored for this exercise. A real deployment needs an audit trail — which label,
which verdict, which rule, when, reviewed by whom — but that is a records
management decision with retention policy attached, not a prototype decision.

---

## Not implemented

**Type size and contrast measurement.** 27 CFR 16.22 sets minimum type sizes for
the warning by container volume, and Jenny mentioned applicants shrinking it.
Checking that needs physical dimensions, which a submitted image does not carry
without a known reference scale. The prototype checks wording and capitalization,
which are the parts an image can answer.

**Poor quality image handling.** Jenny asked about skew, glare and bad lighting.
Partly addressed: images are EXIF-rotated and downscaled, and the extractor is
asked to report what it could not read, which surfaces in the interface as a
legibility note rather than a silent absence. Not addressed: deskewing, glare
removal, or contrast normalization. The honest position is that a label the model
cannot read should return **Review** and say why, which it does.

**Non-English labels.** Imports carry foreign-language text. Out of scope.

**Class/type validation.** The prototype checks the label against the
application. It does not check either against the TTB standards of identity — a
product could be labeled consistently and still be misclassified.

**Authentication, rate limiting, audit logging.** Prototype.

---

## What would come next

In rough order of value per unit of work:

1. **Audit logging.** Nothing else on this list matters without it, and it is the
   gap between a demo and something an agency could pilot.
2. **Multi-panel artwork.** The most common real-world case the prototype misses.
3. **A reviewer feedback loop.** Every time an agent overrides a verdict, that is
   a labeled example. Capturing overrides is how the fuzzy thresholds get tuned
   from evidence instead of from judgment — and those thresholds are currently
   the least evidence-based numbers in the system.
4. **Escalation on low legibility.** Retry with a larger model before returning
   Review.
5. **Batch import from a spreadsheet.** Sarah's importers submit in bulk and
   almost certainly have a manifest already.
