# NISO STS 1.2 interchange DTD (MathML 3)

Vendored copy of the **NISO STS (Standards Tag Suite) v1.2 interchange** DTD set
(MathML 3 variant), used to validate the generated `spec_sts.xml`.

- **Entry point:** `NISO-STS-interchange-1-mathml3.dtd`
- **Spec:** ANSI/NISO Z39.102-2022 (STS), <https://www.niso.org/standards-committees/sts>
- **Source of this copy:** the [`sts4i/sts4i-tools`](https://github.com/sts4i/sts4i-tools)
  repository (`schema/nisosts/NISO-STS-interchange-1-2-MathML3-DTD/`), Apache-2.0.
  NISO's own schema distribution is the canonical source; this copy is vendored so
  validation works offline and in CI without a network fetch.

## Usage

CI validates on every build (see `ci/build.sh` → `ci/validate_sts.py`). Locally:

```bash
# Python / lxml (matches CI):
python3 ci/validate_sts.py <build-dir>/spec_sts.xml

# Or with xmllint (ships with macOS):
xmllint --noout \
  --dtdvalid schema/niso-sts-1.2-mathml3/NISO-STS-interchange-1-mathml3.dtd \
  <build-dir>/spec_sts.xml
```
