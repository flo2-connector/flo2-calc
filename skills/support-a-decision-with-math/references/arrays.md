# Arrays: data and grids

A reference file of the skill `support-a-decision-with-math`, for its steps 5 and 7: give data as an array, not as one
node per number. The rules (`length` for n, statistics named) are in `SKILL.md`.

- An array is an input whose value is `{"array": [...], "unit": "..."}`: a list of numbers as text, or a list of
  rows for a grid, with ONE unit given once. `{"id": "t", "value": {"array": ["0", "2", "4"], "unit": "s"},
  "source": "frame times"}`.
- Every operator works element by element on arrays, and a single value meets every element: `sub` of an array and
  its mean is every deviation. A column (`column`) meets a row as a grid.
- Reduce with `sum`, `mean`, `min`, `max`, `product`, `count_true`, `any`, `all` (add `"axis": 0` or `1` for each
  column or row of a grid). Compare and combine for "how many are out of range": `lt`, `gt`, `or`, `count_true`.
- A straight-line fit is `fit_slope`, `fit_intercept`, `fit_slope_se`, `fit_intercept_se` and `fit_residual_se`,
  each with args `[x, y]`. For example, a rate with its standard error, in four nodes:

  ```json
  {"nodes": [
    {"id": "t", "value": {"array": ["0", "2", "4", "6", "8", "10"], "unit": "s"}, "source": "frame times"},
    {"id": "y", "value": {"array": ["0.0000", "0.0291", "0.0574", "0.0868", "0.1152", "0.1447"], "unit": "deg"},
     "source": "along-track angle, frames 1 to 6"},
    {"id": "slope", "op": "fit_slope", "args": ["t", "y"]},
    {"id": "slope_se", "op": "fit_slope_se", "args": ["t", "y"]}]}
  ```

  The slope comes back exact (`316/21875 deg/s`, 0.014446 deg/s) and its standard error correctly rounded
  (0.0000374983 deg/s).
- The FFT is `fft` and `ifft` (1-D), `fft2` and `ifft2` (a grid), numpy's convention. Take a spectrum apart with
  `abs` (the modulus), `phase` (with `"unit": "deg"` or `"rad"`), `real`, `imag`. A small 2-D example:

  ```json
  {"nodes": [
    {"id": "g", "value": {"array": [["1", "2", "1", "0"], ["2", "4", "2", "0"], ["1", "2", "1", "0"],
      ["0", "0", "0", "0"]], "unit": "V"}, "source": "a 4 x 4 aperture"},
    {"id": "spectrum", "op": "fft2", "args": ["g"]},
    {"id": "power", "op": "abs", "args": ["spectrum"]},
    {"id": "dc", "op": "max", "args": ["power"]}]}
  ```

- A grid over two axes is `linspace` on each, `column` on one, and their element-wise product or sum: the
  discretised integral of f(x, y) exp(...) is a few nodes ending in one `sum`.
- Large data, run locally, can come from a file inside the folder flo2-calc was started in:
  `{"file": "data/readings.csv", "unit": "mm"}`. The record keeps the file's sha256, so keep the file with it. On
  flo2.io, give the array inline.
- An exact array stays exact. An FFT, a function over an array (`exp`, `sqrt`, `sin` ...), an array of more than
  the host's exact limit (65,536 elements on a laptop, 4,096 on flo2.io), or anything mixed with one, comes back
  labelled `"float64"`, with `error_at_most` (a rigorous bound on every element) and `how` (what that bound rests
  on). Arrays of more than 1,024 elements come back as their first values, least, greatest and sha256: reduce them,
  or pick an element with `element`, rather than ask for every value.
- An exact array result whose elements include fractions also comes back with `readable`: those elements as
  decimals of 6 significant digits, labelled as a rendering. Quote the rendering to the person; the exact values
  (the record holds only them) are the result.
- `"kind": "shape_mismatch"`: two arrays whose shapes do not combine. Say which way they meet (`column`,
  `transpose`), or fix the data.
