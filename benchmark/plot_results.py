"""
Parse raw benchmark output and plot results in linear scale.

Expected input format (one line per data point):
  benchmark.js {'n': ..., 'rust-driver': [...], 'lib': [...]} {'n': ..., 'rust-driver': [...], 'lib': [...]}

Usage:
  python plot_results.py                            # uses embedded data
  python plot_results.py results.txt                # one file
  python plot_results.py file1.txt file2.txt        # compare two runs (different colors)
  python plot_results.py file1.txt file2.txt --labels "before" "after"
"""

import sys
import ast
import re
import os
import argparse
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

# One linestyle per dataset so two runs of the same lib are easy to distinguish
DATASET_STYLES = [
    {"linestyle": "-",  "marker": "o", "markersize": 4},
    {"linestyle": "--", "marker": "s", "markersize": 4},
    {"linestyle": ":",  "marker": "^", "markersize": 4},
    {"linestyle": "-.", "marker": "D", "markersize": 4},
]


RAW_DATA = """\
concurrent_insert.js {'n': 62500.0, 'rust-driver': [0.47000000000000003], 'scylladb-driver-alpha': [1.01], 'cassandra-driver': [4.17]} {'n': 62500.0, 'rust-driver': [42.49609375], 'scylladb-driver-alpha': [168.81640625], 'cassandra-driver': [240.70703125]}
concurrent_insert.js {'n': 250000.0, 'rust-driver': [1.05], 'scylladb-driver-alpha': [2.37], 'cassandra-driver': [5.18]} {'n': 250000.0, 'rust-driver': [42.83984375], 'scylladb-driver-alpha': [340.25390625], 'cassandra-driver': [558.86328125]}
concurrent_insert.js {'n': 1000000.0, 'rust-driver': [3.24], 'scylladb-driver-alpha': [8.36], 'cassandra-driver': [14.12]} {'n': 1000000.0, 'rust-driver': [42.5546875], 'scylladb-driver-alpha': [1007.0234375], 'cassandra-driver': [1081.40625]}
concurrent_insert.js {'n': 4000000.0, 'rust-driver': [17.32], 'scylladb-driver-alpha': [43.11], 'cassandra-driver': [55.12]} {'n': 4000000.0, 'rust-driver': [42.6015625], 'scylladb-driver-alpha': [1515.0], 'cassandra-driver': [1919.17578125]}
insert.js {'n': 6250.0, 'rust-driver': [0.94], 'scylladb-driver-alpha': [0.87], 'cassandra-driver': [4.07]} {'n': 6250.0, 'rust-driver': [42.82421875], 'scylladb-driver-alpha': [67.83203125], 'cassandra-driver': [79.265625]}
insert.js {'n': 25000.0, 'rust-driver': [1.57], 'scylladb-driver-alpha': [2.07], 'cassandra-driver': [4.22]} {'n': 25000.0, 'rust-driver': [42.8515625], 'scylladb-driver-alpha': [68.40234375], 'cassandra-driver': [81.5703125]}
insert.js {'n': 100000.0, 'rust-driver': [4.58], 'scylladb-driver-alpha': [6.35], 'cassandra-driver': [10.89]} {'n': 100000.0, 'rust-driver': [42.97265625], 'scylladb-driver-alpha': [68.796875], 'cassandra-driver': [86.0390625]}
insert.js {'n': 400000.0, 'rust-driver': [15.59], 'scylladb-driver-alpha': [22.71], 'cassandra-driver': [29.95]} {'n': 400000.0, 'rust-driver': [42.9140625], 'scylladb-driver-alpha': [68.78515625], 'cassandra-driver': [85.8828125]}
select.js {'n': 1562.5, 'rust-driver': [1.42], 'scylladb-driver-alpha': [1.41], 'cassandra-driver': [2.6]} {'n': 1562.5, 'rust-driver': [42.95703125], 'scylladb-driver-alpha': [69.0078125], 'cassandra-driver': [80.609375]}
select.js {'n': 6250.0, 'rust-driver': [3.29], 'scylladb-driver-alpha': [3.72], 'cassandra-driver': [6.29]} {'n': 6250.0, 'rust-driver': [42.7109375], 'scylladb-driver-alpha': [69.2265625], 'cassandra-driver': [80.74609375]}
select.js {'n': 25000.0, 'rust-driver': [12.270000000000001], 'scylladb-driver-alpha': [12.98], 'cassandra-driver': [13.13]} {'n': 25000.0, 'rust-driver': [42.8984375], 'scylladb-driver-alpha': [69.20703125], 'cassandra-driver': [82.9453125]}
select.js {'n': 100000.0, 'rust-driver': [47.21], 'scylladb-driver-alpha': [51.25], 'cassandra-driver': [46.81]} {'n': 100000.0, 'rust-driver': [42.86328125], 'scylladb-driver-alpha': [69.33984375], 'cassandra-driver': [83.890625]}
concurrent_select.js {'n': 6250.0, 'rust-driver': [0.73], 'scylladb-driver-alpha': [0.76], 'cassandra-driver': [4.36]} {'n': 6250.0, 'rust-driver': [42.88671875], 'scylladb-driver-alpha': [97.796875], 'cassandra-driver': [106.81640625]}
concurrent_select.js {'n': 25000.0, 'rust-driver': [2.0500000000000003], 'scylladb-driver-alpha': [2.29], 'cassandra-driver': [4.03]} {'n': 25000.0, 'rust-driver': [42.55078125], 'scylladb-driver-alpha': [163.87890625], 'cassandra-driver': [180.67578125]}
concurrent_select.js {'n': 100000.0, 'rust-driver': [8.15], 'scylladb-driver-alpha': [7.85], 'cassandra-driver': [11.09]} {'n': 100000.0, 'rust-driver': [42.80078125], 'scylladb-driver-alpha': [406.2578125], 'cassandra-driver': [451.38671875]}
concurrent_select.js {'n': 400000.0, 'rust-driver': [31.980000000000004], 'scylladb-driver-alpha': [32.07], 'cassandra-driver': [42.36]} {'n': 400000.0, 'rust-driver': [42.859375], 'scylladb-driver-alpha': [1383.49609375], 'cassandra-driver': [1488.078125]}
batch.js {'n': 46875.0, 'rust-driver': [0.6799999999999999], 'scylladb-driver-alpha': [0.89], 'cassandra-driver': [2.21]} {'n': 46875.0, 'rust-driver': [42.95703125], 'scylladb-driver-alpha': [96.78125], 'cassandra-driver': [109.09765625]}
batch.js {'n': 187500.0, 'rust-driver': [1.65], 'scylladb-driver-alpha': [1.75], 'cassandra-driver': [3.78]} {'n': 187500.0, 'rust-driver': [42.74609375], 'scylladb-driver-alpha': [121.26953125], 'cassandra-driver': [110.31640625]}
batch.js {'n': 750000.0, 'rust-driver': [3.86], 'scylladb-driver-alpha': [5.13], 'cassandra-driver': [7.63]} {'n': 750000.0, 'rust-driver': [42.859375], 'scylladb-driver-alpha': [119.734375], 'cassandra-driver': [113.1015625]}
batch.js {'n': 3000000.0, 'rust-driver': [16.84], 'scylladb-driver-alpha': [20.83], 'cassandra-driver': [23.74]} {'n': 3000000.0, 'rust-driver': [43.0703125], 'scylladb-driver-alpha': [120.3046875], 'cassandra-driver': [112.14453125]}
paging.js {'n': 62.5, 'rust-driver': [1.18], 'scylladb-driver-alpha': [1.13], 'cassandra-driver': [2.85]} {'n': 62.5, 'rust-driver': [42.0390625], 'scylladb-driver-alpha': [67.73828125], 'cassandra-driver': [78.73828125]}
paging.js {'n': 250.0, 'rust-driver': [1.93], 'scylladb-driver-alpha': [2.43], 'cassandra-driver': [3.93]} {'n': 250.0, 'rust-driver': [42.55859375], 'scylladb-driver-alpha': [70.33984375], 'cassandra-driver': [80.328125]}
paging.js {'n': 1000.0, 'rust-driver': [6.43], 'scylladb-driver-alpha': [7.65], 'cassandra-driver': [8.3]} {'n': 1000.0, 'rust-driver': [42.546875], 'scylladb-driver-alpha': [70.2578125], 'cassandra-driver': [83.5078125]}
paging.js {'n': 4000.0, 'rust-driver': [22.61], 'scylladb-driver-alpha': [27.3], 'cassandra-driver': [24.37]} {'n': 4000.0, 'rust-driver': [42.69921875], 'scylladb-driver-alpha': [71.00390625], 'cassandra-driver': [84.68359375]}
concurrent_paging.js {'n': 20.0, 'rust-driver': [0.84], 'scylladb-driver-alpha': [0.84], 'cassandra-driver': [4.19]} {'n': 20.0, 'rust-driver': [42.9921875], 'scylladb-driver-alpha': [73.04296875], 'cassandra-driver': [94.38671875]}
concurrent_paging.js {'n': 80.0, 'rust-driver': [1.78], 'scylladb-driver-alpha': [2.2], 'cassandra-driver': [3.15]} {'n': 80.0, 'rust-driver': [42.6796875], 'scylladb-driver-alpha': [79.33984375], 'cassandra-driver': [98.65625]}
concurrent_paging.js {'n': 320.0, 'rust-driver': [5.989999999999999], 'scylladb-driver-alpha': [7.16], 'cassandra-driver': [7.82]} {'n': 320.0, 'rust-driver': [42.87890625], 'scylladb-driver-alpha': [83.984375], 'cassandra-driver': [107.81640625]}
concurrent_paging.js {'n': 1280.0, 'rust-driver': [22.76], 'scylladb-driver-alpha': [26.65], 'cassandra-driver': [26.22]} {'n': 1280.0, 'rust-driver': [42.51953125], 'scylladb-driver-alpha': [107.4609375], 'cassandra-driver': [100.78515625]}
large_select.js {'n': 62.5, 'rust-driver': [0.95], 'scylladb-driver-alpha': [1.15], 'cassandra-driver': [4.18]} {'n': 62.5, 'rust-driver': [42.69921875], 'scylladb-driver-alpha': [91.75390625], 'cassandra-driver': [96.609375]}
large_select.js {'n': 250.0, 'rust-driver': [1.73], 'scylladb-driver-alpha': [2.61], 'cassandra-driver': [3.38]} {'n': 250.0, 'rust-driver': [43.16796875], 'scylladb-driver-alpha': [92.9140625], 'cassandra-driver': [91.84375]}
large_select.js {'n': 1000.0, 'rust-driver': [5.22], 'scylladb-driver-alpha': [6.61], 'cassandra-driver': [8.98]} {'n': 1000.0, 'rust-driver': [42.67578125], 'scylladb-driver-alpha': [94.84765625], 'cassandra-driver': [97.4453125]}
large_select.js {'n': 4000.0, 'rust-driver': [19.58], 'scylladb-driver-alpha': [25.18], 'cassandra-driver': [29.13]} {'n': 4000.0, 'rust-driver': [42.9375], 'scylladb-driver-alpha': [96.8671875], 'cassandra-driver': [99.0078125]}
deser.js {'n': 31.25, 'rust-driver': [0.31], 'scylladb-driver-alpha': [0.54], 'cassandra-driver': [3.4]} {'n': 31.25, 'rust-driver': [43.0859375], 'scylladb-driver-alpha': [66.05078125], 'cassandra-driver': [70.73828125]}
deser.js {'n': 125.0, 'rust-driver': [0.61], 'scylladb-driver-alpha': [1.04], 'cassandra-driver': [3.14]} {'n': 125.0, 'rust-driver': [43.03515625], 'scylladb-driver-alpha': [74.515625], 'cassandra-driver': [78.84765625]}
deser.js {'n': 500.0, 'rust-driver': [1.79], 'scylladb-driver-alpha': [2.47], 'cassandra-driver': [5.16]} {'n': 500.0, 'rust-driver': [42.71875], 'scylladb-driver-alpha': [93.390625], 'cassandra-driver': [97.4609375]}
deser.js {'n': 2000.0, 'rust-driver': [18.51], 'scylladb-driver-alpha': [31.04], 'cassandra-driver': [35.33]} {'n': 2000.0, 'rust-driver': [42.2890625], 'scylladb-driver-alpha': [130.09765625], 'cassandra-driver': [144.28125]}
concurrent_deser.js {'n': 31.25, 'rust-driver': [0.51], 'scylladb-driver-alpha': [0.53], 'cassandra-driver': [3.4]} {'n': 31.25, 'rust-driver': [42.66015625], 'scylladb-driver-alpha': [67.265625], 'cassandra-driver': [72.796875]}
concurrent_deser.js {'n': 125.0, 'rust-driver': [0.53], 'scylladb-driver-alpha': [0.66], 'cassandra-driver': [3.01]} {'n': 125.0, 'rust-driver': [43.0390625], 'scylladb-driver-alpha': [126.234375], 'cassandra-driver': [118.22265625]}
concurrent_deser.js {'n': 500.0, 'rust-driver': [0.6699999999999999], 'scylladb-driver-alpha': [1.76], 'cassandra-driver': [3.81]} {'n': 500.0, 'rust-driver': [42.71484375], 'scylladb-driver-alpha': [765.33984375], 'cassandra-driver': [572.26953125]}
concurrent_deser.js {'n': 2000.0, 'rust-driver': [4.12], 'scylladb-driver-alpha': [32.38], 'cassandra-driver': [43.2]} {'n': 2000.0, 'rust-driver': [156.6015625], 'scylladb-driver-alpha': [5584.5546875], 'cassandra-driver': [4125.62890625]}
ser.js {'n': 14.0625, 'rust-driver': [0.45], 'scylladb-driver-alpha': [0.51], 'cassandra-driver': [5.04]} {'n': 14.0625, 'rust-driver': [43.0546875], 'scylladb-driver-alpha': [63.9765625], 'cassandra-driver': [70.88671875]}
ser.js {'n': 56.25, 'rust-driver': [0.6], 'scylladb-driver-alpha': [1.2], 'cassandra-driver': [4.73]} {'n': 56.25, 'rust-driver': [42.703125], 'scylladb-driver-alpha': [71.4375], 'cassandra-driver': [81.8828125]}
ser.js {'n': 225.0, 'rust-driver': [4.2299999999999995], 'scylladb-driver-alpha': [6.32], 'cassandra-driver': [8.39]} {'n': 225.0, 'rust-driver': [43.125], 'scylladb-driver-alpha': [69.9375], 'cassandra-driver': [87.51953125]}
ser.js {'n': 900.0, 'rust-driver': [56.64], 'scylladb-driver-alpha': [92.85], 'cassandra-driver': [104.22999999999999]} {'n': 900.0, 'rust-driver': [43.34375], 'scylladb-driver-alpha': [74.48828125], 'cassandra-driver': [96.1328125]}
concurrent_ser.js {'n': 18.75, 'rust-driver': [1.02], 'scylladb-driver-alpha': [0.62], 'cassandra-driver': [2.92]} {'n': 18.75, 'rust-driver': [42.609375], 'scylladb-driver-alpha': [66.37109375], 'cassandra-driver': [72.73828125]}
concurrent_ser.js {'n': 75.0, 'rust-driver': [0.39], 'scylladb-driver-alpha': [0.86], 'cassandra-driver': [3.17]} {'n': 75.0, 'rust-driver': [42.54296875], 'scylladb-driver-alpha': [108.19921875], 'cassandra-driver': [110.10546875]}
concurrent_ser.js {'n': 300.0, 'rust-driver': [0.95], 'scylladb-driver-alpha': [2.39], 'cassandra-driver': [4.61]} {'n': 300.0, 'rust-driver': [42.99609375], 'scylladb-driver-alpha': [286.81640625], 'cassandra-driver': [294.39453125]}
concurrent_ser.js {'n': 1200.0, 'rust-driver': [13.200000000000001], 'scylladb-driver-alpha': [38.5], 'cassandra-driver': [47.23]} {'n': 1200.0, 'rust-driver': [43.4453125], 'scylladb-driver-alpha': [2798.984375], 'cassandra-driver': [3150.9375]}
"""

# Old dataset: scylladb-driver-alpha only (no rust-driver data), kept for comparison.
# The lib is renamed to 'scylladb-driver-alpha(old)' to distinguish it on the plot.
RAW_DATA_OLD = """\
concurrent_insert.js {'n': 62500.0, 'scylladb-driver-alpha(old)': [1.39]} {'n': 62500.0, 'scylladb-driver-alpha(old)': [147.10546875]}
concurrent_insert.js {'n': 250000.0, 'scylladb-driver-alpha(old)': [3.49]} {'n': 250000.0, 'scylladb-driver-alpha(old)': [321.58984375]}
concurrent_insert.js {'n': 1000000.0, 'scylladb-driver-alpha(old)': [11.5]} {'n': 1000000.0, 'scylladb-driver-alpha(old)': [990.125]}
concurrent_insert.js {'n': 4000000.0, 'scylladb-driver-alpha(old)': [64.86]} {'n': 4000000.0, 'scylladb-driver-alpha(old)': [1521.41015625]}
insert.js {'n': 6250.0, 'scylladb-driver-alpha(old)': [1.44]} {'n': 6250.0, 'scylladb-driver-alpha(old)': [69.2265625]}
insert.js {'n': 25000.0, 'scylladb-driver-alpha(old)': [2.56]} {'n': 25000.0, 'scylladb-driver-alpha(old)': [69.87109375]}
insert.js {'n': 100000.0, 'scylladb-driver-alpha(old)': [8.36]} {'n': 100000.0, 'scylladb-driver-alpha(old)': [70.609375]}
insert.js {'n': 400000.0, 'scylladb-driver-alpha(old)': [32.24]} {'n': 400000.0, 'scylladb-driver-alpha(old)': [72.125]}
select.js {'n': 1562.5, 'scylladb-driver-alpha(old)': [1.61]} {'n': 1562.5, 'scylladb-driver-alpha(old)': [70.55078125]}
select.js {'n': 6250.0, 'scylladb-driver-alpha(old)': [4.0]} {'n': 6250.0, 'scylladb-driver-alpha(old)': [68.26953125]}
select.js {'n': 25000.0, 'scylladb-driver-alpha(old)': [13.43]} {'n': 25000.0, 'scylladb-driver-alpha(old)': [70.66796875]}
select.js {'n': 100000.0, 'scylladb-driver-alpha(old)': [53.57]} {'n': 100000.0, 'scylladb-driver-alpha(old)': [70.68359375]}
concurrent_select.js {'n': 6250.0, 'scylladb-driver-alpha(old)': [0.8]} {'n': 6250.0, 'scylladb-driver-alpha(old)': [101.9296875]}
concurrent_select.js {'n': 25000.0, 'scylladb-driver-alpha(old)': [2.66]} {'n': 25000.0, 'scylladb-driver-alpha(old)': [165.26953125]}
concurrent_select.js {'n': 100000.0, 'scylladb-driver-alpha(old)': [9.7]} {'n': 100000.0, 'scylladb-driver-alpha(old)': [409.84765625]}
concurrent_select.js {'n': 400000.0, 'scylladb-driver-alpha(old)': [37.34]} {'n': 400000.0, 'scylladb-driver-alpha(old)': [1399.34375]}
batch.js {'n': 46875.0, 'scylladb-driver-alpha(old)': [0.77]} {'n': 46875.0, 'scylladb-driver-alpha(old)': [99.6796875]}
batch.js {'n': 187500.0, 'scylladb-driver-alpha(old)': [1.9]} {'n': 187500.0, 'scylladb-driver-alpha(old)': [129.99609375]}
batch.js {'n': 750000.0, 'scylladb-driver-alpha(old)': [5.37]} {'n': 750000.0, 'scylladb-driver-alpha(old)': [130.84765625]}
batch.js {'n': 3000000.0, 'scylladb-driver-alpha(old)': [23.15]} {'n': 3000000.0, 'scylladb-driver-alpha(old)': [132.41796875]}
paging.js {'n': 62.5, 'scylladb-driver-alpha(old)': [1.67]} {'n': 62.5, 'scylladb-driver-alpha(old)': [68.7265625]}
paging.js {'n': 250.0, 'scylladb-driver-alpha(old)': [3.6]} {'n': 250.0, 'scylladb-driver-alpha(old)': [70.828125]}
paging.js {'n': 1000.0, 'scylladb-driver-alpha(old)': [9.65]} {'n': 1000.0, 'scylladb-driver-alpha(old)': [72.0390625]}
paging.js {'n': 4000.0, 'scylladb-driver-alpha(old)': [36.76]} {'n': 4000.0, 'scylladb-driver-alpha(old)': [72.875]}
concurrent_paging.js {'n': 20.0, 'scylladb-driver-alpha(old)': [0.97]} {'n': 20.0, 'scylladb-driver-alpha(old)': [79.5078125]}
concurrent_paging.js {'n': 80.0, 'scylladb-driver-alpha(old)': [2.33]} {'n': 80.0, 'scylladb-driver-alpha(old)': [87.7734375]}
concurrent_paging.js {'n': 320.0, 'scylladb-driver-alpha(old)': [8.46]} {'n': 320.0, 'scylladb-driver-alpha(old)': [113.78125]}
concurrent_paging.js {'n': 1280.0, 'scylladb-driver-alpha(old)': [34.84]} {'n': 1280.0, 'scylladb-driver-alpha(old)': [116.96484375]}
large_select.js {'n': 62.5, 'scylladb-driver-alpha(old)': [1.49]} {'n': 62.5, 'scylladb-driver-alpha(old)': [93.6953125]}
large_select.js {'n': 250.0, 'scylladb-driver-alpha(old)': [2.57]} {'n': 250.0, 'scylladb-driver-alpha(old)': [94.71875]}
large_select.js {'n': 1000.0, 'scylladb-driver-alpha(old)': [6.91]} {'n': 1000.0, 'scylladb-driver-alpha(old)': [94.40234375]}
large_select.js {'n': 4000.0, 'scylladb-driver-alpha(old)': [25.28]} {'n': 4000.0, 'scylladb-driver-alpha(old)': [96.57421875]}
deser.js {'n': 31.25, 'scylladb-driver-alpha(old)': [0.8]} {'n': 31.25, 'scylladb-driver-alpha(old)': [66.5]}
deser.js {'n': 125.0, 'scylladb-driver-alpha(old)': [0.69]} {'n': 125.0, 'scylladb-driver-alpha(old)': [75.859375]}
deser.js {'n': 500.0, 'scylladb-driver-alpha(old)': [2.28]} {'n': 500.0, 'scylladb-driver-alpha(old)': [97.85546875]}
deser.js {'n': 2000.0, 'scylladb-driver-alpha(old)': [27.86]} {'n': 2000.0, 'scylladb-driver-alpha(old)': [136.40234375]}
concurrent_deser.js {'n': 31.25, 'scylladb-driver-alpha(old)': [0.7]} {'n': 31.25, 'scylladb-driver-alpha(old)': [68.26171875]}
concurrent_deser.js {'n': 125.0, 'scylladb-driver-alpha(old)': [0.46]} {'n': 125.0, 'scylladb-driver-alpha(old)': [127.98828125]}
concurrent_deser.js {'n': 500.0, 'scylladb-driver-alpha(old)': [2.12]} {'n': 500.0, 'scylladb-driver-alpha(old)': [671.78125]}
concurrent_deser.js {'n': 2000.0, 'scylladb-driver-alpha(old)': [33.68]} {'n': 2000.0, 'scylladb-driver-alpha(old)': [5288.40625]}
ser.js {'n': 14.0625, 'scylladb-driver-alpha(old)': [0.8]} {'n': 14.0625, 'scylladb-driver-alpha(old)': [65.453125]}
ser.js {'n': 56.25, 'scylladb-driver-alpha(old)': [1.28]} {'n': 56.25, 'scylladb-driver-alpha(old)': [71.796875]}
ser.js {'n': 225.0, 'scylladb-driver-alpha(old)': [6.57]} {'n': 225.0, 'scylladb-driver-alpha(old)': [70.96875]}
ser.js {'n': 900.0, 'scylladb-driver-alpha(old)': [99.39]} {'n': 900.0, 'scylladb-driver-alpha(old)': [76.3046875]}
concurrent_ser.js {'n': 18.75, 'scylladb-driver-alpha(old)': [0.81]} {'n': 18.75, 'scylladb-driver-alpha(old)': [72.1875]}
concurrent_ser.js {'n': 75.0, 'scylladb-driver-alpha(old)': [0.68]} {'n': 75.0, 'scylladb-driver-alpha(old)': [104.390625]}
concurrent_ser.js {'n': 300.0, 'scylladb-driver-alpha(old)': [2.68]} {'n': 300.0, 'scylladb-driver-alpha(old)': [268.2578125]}
concurrent_ser.js {'n': 1200.0, 'scylladb-driver-alpha(old)': [43.1]} {'n': 1200.0, 'scylladb-driver-alpha(old)': [2774.55078125]}
"""


# ---------- parsing ----------

LINE_RE = re.compile(
    r'^(\S+\.js)\s+(\{.*?\})\s+(\{.*?\})$'
)


def parse_lines(text):
    """
    Parse raw benchmark output lines and return two nested dicts:
      df[benchmark]     -> list of {n, lib: [values], ...}   (time)
      df_mem[benchmark] -> list of {n, lib: [values], ...}   (memory)
    """
    df_rows = defaultdict(list)
    df_mem_rows = defaultdict(list)

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = LINE_RE.match(line)
        if not m:
            print(f"WARNING: could not parse line: {line!r}", file=sys.stderr)
            continue
        bench = m.group(1)
        time_dict = ast.literal_eval(m.group(2))
        mem_dict = ast.literal_eval(m.group(3))
        df_rows[bench].append(time_dict)
        df_mem_rows[bench].append(mem_dict)

    # Convert to DataFrames keyed by benchmark name
    libs = None
    df = {}
    df_mem = {}
    for bench in df_rows:
        rows = df_rows[bench]
        mem_rows = df_mem_rows[bench]
        if libs is None:
            libs = [k for k in rows[0].keys() if k != 'n']
        df[bench] = pd.DataFrame(rows)
        df_mem[bench] = pd.DataFrame(mem_rows)

    return df, df_mem, libs


# ---------- plotting ----------

def _means_stds(series):
    means = series.apply(lambda v: np.mean(v) if isinstance(v, list) else v)
    stds  = series.apply(lambda v: np.std(v)  if isinstance(v, list) else 0.0)
    return means, stds


def plot_all_datasets(datasets, output_path="graph_linear.png"):
    """
    datasets : list of (df, df_mem, libs, label)
      - df / df_mem : dicts of benchmark_name -> DataFrame
      - libs        : list of lib names present in this dataset
      - label       : display name for this dataset (may be "")
    Colors are assigned per lib; line styles are assigned per dataset.
    """
    # Collect the union of all benchmark names (preserving first-seen order)
    all_benches = list(dict.fromkeys(
        bench for df, _, _, _ in datasets for bench in df
    ))
    # Collect the union of all lib names
    all_libs = list(dict.fromkeys(
        lib for _, _, libs, _ in datasets for lib in libs
    ))

    multi = len(datasets) > 1
    color_cycle = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    lib_color = {lib: color_cycle[i % len(color_cycle)] for i, lib in enumerate(all_libs)}

    cols = 4
    rows_time = (len(all_benches) + cols - 1) // cols
    rows_mem  = (len(all_benches) + cols - 1) // cols
    total_rows = rows_time + rows_mem

    fig, axes = plt.subplots(
        total_rows, cols,
        figsize=(20, 5 * total_rows),
        facecolor="white",
    )
    axes = axes.flatten()

    def _draw_series(ax, data, libs, d_idx, label, ylabel):
        style = DATASET_STYLES[d_idx % len(DATASET_STYLES)]
        for lib in libs:
            if lib not in data.columns:
                continue
            means, stds = _means_stds(data[lib])
            legend_label = f"{lib} ({label})" if multi and label else lib
            ax.errorbar(
                data["n"], means, yerr=stds,
                label=legend_label,
                color=lib_color[lib],
                linewidth=2, capsize=5,
                **style,
            )
        ax.set_xlabel("Number of requests")
        ax.set_ylabel(ylabel)

    # --- Time ---
    fig.text(0.5, 0.98, "Time", ha="center", fontsize=16, fontweight="bold")
    for i, bench in enumerate(all_benches):
        ax = axes[i]
        ax.set_facecolor("white")
        for d_idx, (df, _, libs, label) in enumerate(datasets):
            if bench not in df:
                continue
            _draw_series(ax, df[bench], libs, d_idx, label, "Time [s]")
        ax.set_title(f"Benchmark - {bench.split('.')[0]}")
        ax.legend()

    for j in range(len(all_benches), rows_time * cols):
        axes[j].axis("off")

    # --- Memory ---
    start = rows_time * cols
    memory_label_y = 1 - (rows_time / total_rows) + 0.01
    fig.text(0.5, memory_label_y, "Memory", ha="center", fontsize=16, fontweight="bold")
    for i, bench in enumerate(all_benches):
        ax = axes[start + i]
        ax.set_facecolor("white")
        for d_idx, (_, df_mem, libs, label) in enumerate(datasets):
            if bench not in df_mem:
                continue
            _draw_series(ax, df_mem[bench], libs, d_idx, label, "Memory [MiB]")
        ax.set_title(f"Benchmark - {bench.split('.')[0]}")
        ax.legend()

    for j in range(start + len(all_benches), total_rows * cols):
        axes[j].axis("off")

    plt.style.use("default")
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.subplots_adjust(hspace=0.4)
    plt.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path}")


# ---------- main ----------

def _filter_libs(libs, df):
    """Drop libs that have no data (e.g. empty rust-driver placeholders)."""
    return [lib for lib in libs if any(
        any((isinstance(v, list) and len(v) > 0) for v in df[bench][lib])
        for bench in df if lib in df[bench].columns
    )]


def main():
    parser = argparse.ArgumentParser(
        description="Plot benchmark results in linear scale. "
                    "Pass one or two result files to compare them."
    )
    parser.add_argument(
        "files", nargs="*",
        help="Path(s) to result file(s). Zero files uses the embedded data.",
    )
    parser.add_argument(
        "--labels", nargs="*", metavar="LABEL",
        help="Display labels for each file (same count as files).",
    )
    parser.add_argument(
        "--output", default="graph_linear.png",
        help="Output image path (default: graph_linear.png).",
    )
    args = parser.parse_args()

    if not args.files:
        texts = [RAW_DATA, RAW_DATA_OLD]
        labels = ["", ""]
    else:
        texts = [open(f).read() for f in args.files]
        if args.labels and len(args.labels) == len(args.files):
            labels = args.labels
        else:
            labels = [os.path.splitext(os.path.basename(f))[0] for f in args.files]

    datasets = []
    for text, label in zip(texts, labels):
        df, df_mem, libs = parse_lines(text)
        libs = _filter_libs(libs, df)
        datasets.append((df, df_mem, libs, label))

    plot_all_datasets(datasets, output_path=args.output)


if __name__ == "__main__":
    main()
