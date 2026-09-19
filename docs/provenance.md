# Provenance and Offline Verification

You have been handed a dataset that claims to be synthetic. This page is how you check that
claim yourself, on your own machine, without contacting anyone — including us.

- [The check, in one command](#the-check-in-one-command)
- [Reading the three lines](#reading-the-three-lines)
- [When a check fails](#when-a-check-fails)
- [What the declaration says](#what-the-declaration-says)
- [Reading the data back](#reading-the-data-back)
- [From Python](#from-python)
- [The chain of trust](#the-chain-of-trust)
- [What this does not prove](#what-this-does-not-prove)

## The check, in one command

Verification is part of the published client and the licence guarantees it stays free: you do
not need a licence key to verify someone else's file, and no network request is made at any
point.

```bash
pip install ai-data-studio
ai-data-studio --verify-report orders.csv
```

```
orders.csv
  PASS  Licence signature valid - issued to key ADS-PRO-00042 (PRO)
  PASS  Declaration signature valid - the declaration was produced by that licence
  PASS  Content digest matches - the file is the data the declaration describes
```

The exit code is `0` when every check passes and `1` when any of them fails, so this drops
into a pipeline. Several files can be given at once; each is reported separately.

`.csv`, `.json`, `.parquet` and the `.pdf` audit report are all accepted — the declaration
travels in CSV comment lines, a top-level `_provenance` key, Parquet schema metadata, and the
PDF's document metadata respectively.

## Reading the three lines

Three separate things are being checked, and a failure tells you which one broke.

| Line | What it establishes |
| --- | --- |
| **Licence signature valid** | The licence embedded in the file was issued by AI Synthetic Data Studio. It is verified against the master public key compiled into this client, so a self-issued licence does not pass. |
| **Declaration signature valid** | The declaration was signed by *that* licence. Each licence carries its own report-signing keypair; only the public half ever enters a file, so copying someone else's licence out of their report does not let you sign your own. |
| **Content digest matches** | The bytes in front of you are the data the declaration describes. The SHA-256 is recomputed from the file and compared. |

The licence key and tier in the first line identify who signed the file. That is the party
accountable for the declaration.

## When a check fails

**The file is not signed at all.** A run without a Pro or Enterprise licence still writes the
declaration — it is simply unsigned, and the tool says so rather than pretending otherwise:

```
orders_unsigned.csv
  FAIL  This file carries no provenance signature; it declares its origin but nothing vouches for it.
```

An unsigned file is not evidence of tampering. It means nobody has vouched for it, and the
header alone is worth exactly as much as the sender's word.

**The data was changed after signing.** Editing a single value breaks the digest while the
signatures still verify, which is what you want to see — it localises the change:

```
orders_tampered.csv
  PASS  Licence signature valid - issued to key ADS-PRO-00042 (PRO)
  PASS  Declaration signature valid - the declaration was produced by that licence
  FAIL  Content digest matches - the file is the data the declaration describes
        The data does not match the digest in the declaration; the file was changed after signing.
```

**The signing licence was revoked.** Revoked keys ship inside the client
(`ai_data_studio/licensing/revoked_keys.json`) and are refused even when their signature is
still cryptographically valid. Update the client to pick up newer revocations.

**Other failures you may see**, each on its own line: the embedded licence was not issued by
us, the declaration was not signed by the licence it names, the licence predates report
signing and carries no report key, or the signature block is malformed.

## What the declaration says

A CSV written with `--provenance` starts like this:

```
# PROVENANCE: 100% Synthetic Data - Non-PII - Generated Locally by AI Synthetic Data Studio. This dataset contains no real personal identifiable information.
# COMPLIANCE: EU AI Act Art. 50 / Non-Personal Data
# GENERATOR: ai-data-studio 2.0.0
# GENERATED_AT: 2026-09-18T21:07:30+00:00
# ROWS: 5
# COLUMNS: 3
# CONTENT_SHA256: 4ca98a4399989dd74d9fb72d92ffa0431444474c15db4d58ea864d98b2f7933a
# PRIVACY_AUDIT: not_performed
# LICENSE_KEY: ADS-PRO-00042
# LICENSE_TIER: pro
# LICENSE_TOKEN: eyJlbWFpbCI6...
# SIGNATURE_SCHEME: ads-ed25519-v1
# SIGNATURE: 3Ay8wYni1Ixx2P/rJlHRmHsh17ELnM0tqB2tqPPTHEartPOa5obxMdQY0X4i6ovzG1W1Fad1/joieV3K1H/kBQ==
order_id,amount,country
```

| Field | Meaning |
| --- | --- |
| `GENERATED_AT` | UTC, to the second. |
| `ROWS` / `COLUMNS` | Shape of the data the digest covers. |
| `CONTENT_SHA256` | Digest of the data itself, not of the file: the header is excluded, so re-exporting the same rows to another format keeps it stable. |
| `RANDOM_SEED` | Present when the contract fixed a seed; the run is reproducible from it. |
| `PRIVACY_AUDIT` | `not_performed` (no audit ran), `no_reference_data` (an audit ran with no real data to compare against, so memorisation could not be measured), or the audit's own verdict. |
| `LICENSE_KEY` / `LICENSE_TIER` / `LICENSE_SEATS` | Who signed, under which edition. `LICENSE_SEATS` is a declaration, not an enforced limit. |
| `LICENSE_TOKEN` | The licence payload plus our signature over it — the public half only. It does not let its holder issue licences or claim the entitlement. |
| `SIGNATURE_SCHEME` / `SIGNATURE` | `ads-ed25519-v1`: Ed25519 over the declaration's canonical JSON, every field except `SIGNATURE` itself. |

Read `PRIVACY_AUDIT` before the rest. `not_performed` means no privacy claim was measured on
this dataset — the signature vouches for where the data came from, not for its privacy
properties.

## Reading the data back

The `#` header is not a comment as far as `pandas` is concerned: `read_csv` raises a
`ParserError` on a provenance file, and Excel treats the first header line as data. Use the
helper, which handles all three formats and unwraps the JSON `{"_provenance", "data"}`
envelope:

```python
from ai_data_studio import read_output

df = read_output("orders.csv")
```

It reads floats with `float_precision="round_trip"`. The default parser drops the last digit,
which is enough to make an untouched file fail its own digest check.

Plain pandas works too: `pd.read_csv(path, comment="#", float_precision="round_trip")`.

## From Python

```python
from ai_data_studio import verify_provenance

result = verify_provenance("orders.csv")

result.ok               # every check passed
result.signed           # False for an unlicensed run
result.license_key      # "ADS-PRO-00042"
result.license_tier     # "pro"
result.email            # who the licence was issued to
result.license_valid    # our signature over the licence payload
result.signature_valid  # that licence's signature over the declaration
result.content_matches  # recomputed digest == declared digest
result.revoked          # licence appears in the shipped revocation list
result.problems         # human-readable reasons, empty when ok

print("\n".join(result.summary_lines()))
```

## The chain of trust

```
master key (ours, offline)
    signs the licence payload, which contains report_public_key
        report_public_key verifies the declaration signature
            the declaration signature covers the dataset digest
                the digest is recomputed from the file you hold
```

Every link is checked locally. The only thing you take from us is the master public key, and
it is compiled into source you can read. Nothing phones home, which is the point for
air-gapped review.

## What this does not prove

The declaration states what the tool measured, and the signature states who stands behind it.
Neither is a certification.

- Whether a dataset may be transferred, published or relied on for a given purpose is the data
  controller's determination, not the generator's.
- An unsigned declaration binds the header to the data, but a party who edits both produces a
  consistent file. Only the signed form resists that.
- `machine_id` and `seats` in the licence are declarations, not enforced limits.
- A matching digest says the file is unchanged since signing. It says nothing about whether the
  inputs to that run were what they should have been.
