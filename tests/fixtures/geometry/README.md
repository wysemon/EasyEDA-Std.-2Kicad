# Pad geometry excerpts

`real_pad_examples.json` contains four unmodified records extracted from
KiCad's EasyEDA Standard test board, **ESP32-PICO-D4 smart watch**.
The JSON records the source URL, Git commit, blob and component contributors.
The source project's **CC-BY-NC-SA 3.0** license is included verbatim here and
applies to these excerpts, separately from the converter's MIT code license.

The switch records contain asymmetric rectangular pads at 124 degrees and
rotated source text. The USB-C record contains a genuine oblong drill with
horizontal hole-center points, local width < height, and rotation 270.
Tests compare geometry with native KiCad's Standard importer and saved output.
A polygon calibration changes a copy of the rectangle's type to POLYGON while
keeping its source vertices. It is a derived test, not a claimed real custom-pad
component. Rear-side calibration is similarly synthetic.
