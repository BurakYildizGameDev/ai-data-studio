<!-- DRAFT: LEGAL REVIEW REQUIRED -->

# AI Synthetic Data Studio — Commercial Licence (Pro)

**Status: draft. This document has not yet been reviewed by a lawyer. Until it has been,
treat it as a statement of intent about what a Pro key buys, not as final legal text.**

This is the second half of a dual-licensing model. The source in this repository is licensed
under the [PolyForm Noncommercial License 1.0.0](LICENSE), which covers everything except
commercial use. This document covers commercial use, and applies only to a holder of a valid
Pro licence key issued through the licensor's Lemon Squeezy store.

It grants rights **in addition to** the licence in [LICENSE](LICENSE). It never takes away a
right that licence gives you. Where the two disagree about what a Pro key permits, this
document governs; the noncommercial licence continues to govern the source itself.

`LICENSE` is unchanged by this file and remains the licence of the repository.

---

## 1. The licence

**Pro — $19, paid once.** One purchase, per named purchaser. The key is issued by the
licensor's store:

    https://ai-synthetic-data-studio.lemonsqueezy.com/checkout/buy/
    17400e93-40b9-47d9-aee2-9eaa676964a0

**Perpetual for the purchased major version.** A key bought against version 2.x licenses
every 2.x release, for as long as you care to run it. There is no renewal, no subscription and
no expiry date on the entitlement: a Pro key that works today works in five years on the same
major version, with or without a network connection. A future major version (3.x) is a
separate purchase, and nothing in this document obliges the licensor to publish one.

Paying once does not make the grant unconditional. It ends only in the narrow cases in
section 5, each of which is something the licence holder does.

## 2. What commercial use a Pro key permits

With a valid Pro key, you may use the software for **commercial use**, including all of:

1. **Generating data commercially.** Produce synthetic datasets in the course of commercial
   activity, at any scale, for any purpose the law allows — including data you sell, ship
   inside a product, or use to train or test a model you sell.
2. **Validating data commercially.** Run the validator, the privacy checks and the
   relational integrity checks over your own data or your client's data as part of paid work.
3. **Client projects.** Independent consultants, freelance ML engineers and agencies may run
   the software on behalf of a client and bill for that work. Deliverables produced for the
   client — datasets, contracts, reports — belong to you and your client, not to the licensor.
4. **Internal company workflows.** Run it inside a company, on company machines, in CI and in
   data pipelines, as part of how the business operates.
5. **Signed provenance and the PDF audit report.** Generate signed provenance declarations
   and the executive PDF audit report, and hand both to clients, auditors, regulators and
   review boards as evidence of how a dataset was produced. Using those reports commercially
   is exactly what the Pro tier is for.

**Output is yours.** The licensor claims no ownership of, and no licence in, the datasets,
schema contracts, reports or PDFs you generate. Nothing produced by the software carries this
licence forward to whoever receives it.

## 3. Seats

A key is issued to the named purchaser. One natural person may use it on as many machines as
they personally work on — a laptop and a desktop are one seat, not two. A second person needs
a second key. Enterprise keys may declare a larger seat count; that count is what applies.

Keys are not transferable between people. A company may reassign a seat when an employee
leaves.

## 4. What a Pro key does not permit

A Pro key licenses **use of the software**. It does not license **redistribution of the
software itself**. Specifically, you may not:

- Sell, resell, rent, sublicense or lease the software, in source or compiled form.
- Repackage it — renamed, rebranded, forked, bundled or embedded — and distribute that
  package for a fee, as a paid product, or as a paid component of one.
- Offer the software itself as a hosted or managed service whose substantial value is the
  software's own functionality (a "SaaS wrapper").
- Distribute a build or derivative that forges, bypasses, disables or misrepresents the
  licence check, or generate, share or sell keys or tokens that imitate ones the licensor
  issues.
- Share your key, publish it, or use it to unlock installs beyond your seat count.

Building your own product that *uses* the software internally is permitted under section 2.
Selling the software *as* the product is not. If the line matters for what you are planning,
ask the licensor for OEM or redistribution terms before you build on it.

Studying the licence and provenance code, testing it against your own keys, and reporting
weaknesses to the licensor remain expressly permitted, as in [LICENSE](LICENSE).

## 5. When the grant ends

The rights in section 2 continue unless one of these happens:

- **Breach.** You do something section 4 forbids. The licensor will give written notice and
  30 days to correct it; the grant ends only if it is not corrected in that window.
- **Reversed payment.** The purchase is refunded, charged back or otherwise reversed. The key
  is then revoked, because it was never paid for.
- **Fraudulent acquisition.** The key was obtained by fraud or by imitating a key the
  licensor issues.

Outside those cases the licensor will not revoke a paid key, will not expire it, and will not
condition it on a network check, a renewal or a future purchase. There is no other termination
right in this document.

If a key is revoked, datasets, reports and signed declarations you already produced stay
valid and stay yours. Revocation is not retroactive.

## 6. Verification is free for everyone, always

Checking a signed dataset or report that someone else produced never requires a licence, a
key, a payment or a network connection — not under this document, and not under
[LICENSE](LICENSE). An auditor receiving a signed file must always be able to verify it
independently. This is a permanent commitment and is not conditioned on anything in this
document.

## 7. Support and updates

Bug fixes and releases within the purchased major version are available to Pro key holders as
they are published. This document does not promise a support response time, a specific
release cadence, or that any particular feature will be built.

## 8. Third-party components

Dependencies keep their own licences, which are unaffected by this document.

## 9. No warranty, no liability

The software is provided "as is", without warranty of any kind. **The validator checks data
against the contract, not against the real world**: a model can declare a relationship that is
wrong for your domain, and the tool will faithfully honour it. Deciding whether generated data
is fit for your purpose is your responsibility, and a signed report attests to how a dataset
was produced, not to whether it is correct for what you do with it.

The No Liability section of [LICENSE](LICENSE) applies to this document in full. Nothing here
excludes liability that cannot lawfully be excluded.

## 10. Getting in touch

Commercial licences, OEM terms, redistribution terms and site licences are available from the
licensor through the store linked in section 1.
