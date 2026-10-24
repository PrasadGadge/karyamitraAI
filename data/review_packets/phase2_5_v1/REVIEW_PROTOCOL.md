# KaryaMitra independent review protocol

All messages and catalogue records in this packet are **synthetic**. Review each message against `catalogue_for_review.csv` before looking at any implementation output. Do not open candidate annotation or evaluation files while reviewing.

For each record in `blind_review_template.json`:

1. Add your non-empty `reviewer_id` or initials.
2. Set `review_status` to `reviewed` only after personally inspecting it. Use `needs_adjudication` if uncertain; do not guess.
3. Enter `correct_item_count`. For every unambiguous item, add an object to `items` with `sku`, `quantity`, `unit`, and `normalized_quantity`. Use a `null` SKU only when product identity is unresolved.
4. Set `ambiguity_requires_clarification`, list missing fields (for example `product`, `quantity`, `unit_conversion`, `price`, or `privacy_masking`), and select `DRAFT`, `NEEDS_CLARIFICATION`, or `VERIFIED`.
5. Explain difficult, malformed, Marathi/Hinglish, or privacy-containing messages briefly. Do not infer a product, a missing quantity, an unconfigured box size, or a price.

Only configured conversions in the catalogue are permitted. A dozen means 12 sellable units only where the product has a `dozen:12` rule. A box is valid only where that product has an explicit `box:N` rule. The 12 locked-test records must not be used to tune a parser, prompt, or business rule.

When finished, save a copy as `completed_review.json` and ask the project owner to run the import command in the README. The importer validates the file and creates a new versioned artifact; it never overwrites the candidate annotations.
