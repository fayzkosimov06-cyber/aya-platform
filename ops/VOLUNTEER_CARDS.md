# Volunteer cards

Staff and the department head manage annual cards under `/administration/cards/`.
The management dashboard, the first sidebar item and the account menu link to
the card workspace. Staff profiles also link to it; eligible volunteer profiles
offer card preparation to staff. Ordinary members, including the president,
can view only their own issued cards under `/my-card/`; they cannot use print,
export, source-image, edition or approval endpoints. Delegated profile permissions
do not change these restrictions.

The initial workspace shows both sides of the actual renderer's design proof,
even before the first edition exists. Its name and AI-generated portrait are
fictional, it contains no seal/signature, and its QR opens the volunteer list.
Opening the sample creates no user, card, edition or private uploaded file.
It cannot be used to issue a demo identity. A member's own profile shows the
issued card, or explains that issuance is still pending; other members cannot
view that card section. Once cards exist, the design proof is collapsed by
default so filtering and bulk printing remain convenient.

1. Add an academic year and upload its genuine seal and director signature.
   Default logos come from the existing AYA/university assets; annual overrides
   are supported. A year runs September 1 through August 31.
2. Prepare a card. Selecting a member fills separate family/given/patronymic
   fields and course from their profile. Family-first is the default. Missing
   components collapse without an empty printed line. Card-specific changes,
   numbering and photographs do not modify profiles. Editing an issued card
   returns it to draft and requires another explicit issue action.
3. Review both sides, then issue the card. Photo, names, membership, year and
   approval assets are checked. Expired, revoked, disabled or ineligible cards
   cannot be printed. Revocation also closes owner previews.
4. Select issued cards (up to 100/request) and download an aggregate press PDF,
   duplex A4 PDF, or ZIP of individual two-sided press PDFs plus a JSON manifest
   and print instructions.

## Print output

- Final trim: 86 x 54 mm. Bleed: 3 mm. Individual press pages: 98 x 66 mm including
  3 mm outside the bleed for crop marks. PDF TrimBox is 86 x 54 mm; BleedBox is
  92 x 60 mm. Pages alternate front/back of each card.
- Noto Sans regular/bold are embedded with Tajik Cyrillic support. Font binaries
  and their SIL OFL license are in `users/card_assets/fonts/`, sourced from
  `https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoSans`.
- PDF and PNG use identical capital-height baselines and rounded portrait
  placement. The three name components share a fitted font size; missing
  components leave no blank rows. The course value sits beneath its label.
- The QR sits on the front beside the three name lines; the fitted name column
  cannot extend into its quiet zone. The back combines the two annual logos
  with the exact department caption, and reserves 23 x 16 mm for the genuine
  seal plus a separate 36 x 10 mm signature slot above the footer. Both sides
  carry the editable card number and academic year. Corner accents are vectors.
- QR modules are vectors in pure K black with a four-module white quiet zone;
  payload is the same configured canonical profile URL as existing profile QRs.
- Images retain their available resolution up to 600 dpi at final placed size.
  No fabricated detail is added to small images. The editor warns below 300 dpi.
- A4 uses 2 columns x 4 rows with symmetric 98 x 66 mm cells and 7/16.5 mm outer
  margins. Reverse placement mirrors columns for long-edge binding or rows for
  short-edge binding, including empty positions on the final sheet. Print at
  100% and verify a single duplex proof before a full run.
- PDFs use RGB artwork; the QR is pure K black. They are not certified PDF/X
  and have no invented printer ICC profile. Agree colour conversion, material
  and corner finishing with the selected printer before production.

## Storage and upgrade

`CARD_PRIVATE_ROOT` defaults to `/srv/aya/private/volunteer_cards` on the VPS.
It must remain outside all public media/static locations. Storage rejects `.url`;
only authenticated, authorized views read assets. Uploaded raster images are
decoded, normalized to PNG with metadata removed and limited to 8 MB / 20 MP.
Owner views are flattened lower-resolution PNGs with a viewing watermark, not
separate stamp/signature files. Screenshots of visible material cannot be
technically prevented.

Migration 0052 creates only `CardEdition` and `VolunteerCard`; it does not alter
existing user rows, points, roles or media. Back up the SQLite database, code,
runtime, public media, private directory (if present), environment and service
configuration before upgrading. Only `aya.service` is restarted. A code rollback
can leave the additive tables in place without restoring an older live database.

QA dependencies (`pypdf`, `pypdfium2`, `zxing-cpp`) are isolated from production.
Regression tests decode real rendered PDF QRs, verify trim/bleed/fonts, partial
duplex sheets, missing name parts, private storage, CSRF, role checks and the
create/issue/view/download/revoke workflow on synthetic accounts only. They
also compare actual PDF/PNG name baselines, decode both QR renderers and verify
initial setup, navigation, sample read-only behavior and profile-card isolation.
The reverse's Tajik department name and full seal/signature bounds are verified
in actual PNG and rendered PDF output. Duplex QR checks scan the front sheets.
