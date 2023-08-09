import argparse
import os

import pandas as pd
import numpy as np

# Define the ArgumentParser
parser = argparse.ArgumentParser("List of natural abundances of the isotopes")

# Add arguments
parser.add_argument(
    "-f",
    "--factor",
    type=float,
    metavar="F",
    help="Correction factor (natural abundances), e.g.:"
    "C: 0.9889434148335, H: 0.99988, N: 0.996323567, O: 0.997574195, S: 0.9493",
)
parser.add_argument(
    "--input", type=str, metavar="data", help="Input file/folder", required=True
)
parser.add_argument(
    "--out_summary", type=str, metavar="output", help="Peptide summary output", required=True
)
parser.add_argument(
    "--out_filtered", type=str, metavar="output", help="Filtered output", required=True
)

# Indicate end of argument definitions and parse args
args = parser.parse_args()

# Benchmarking section
# the functions for optimising calis-p data


def load_calisp_data(filename, factor):
    # (1) load data
    file_count = 1
    if os.path.isdir(filename):
        file_data = []
        file_count = len(os.listdir(filename))
        for f in os.listdir(filename):
            f = os.path.join(filename, f)
            file_data.append(pd.read_feather(f))
            base, _ = os.path.splitext(f)
            file_data[-1].to_csv(f"{base}.tsv", sep="\t", index=False)
        data = pd.concat(file_data)
    else:
        data = pd.read_feather(filename)
        base, _ = os.path.splitext(filename)
        data.to_csv(f"{base}.tsv", sep="\t", index=False)

    file_success_count = len(data["ms_run"].unique())
    # (2) calculate deltas
    # ((1-f)/f) - 1 == 1/f -2

    data["delta_na"] = data["ratio_na"] / ((1 / factor) - 2) * 1000
    data["delta_fft"] = data["ratio_fft"] / ((1 / factor) - 2) * 1000
    print(
        f"Loaded {len(data.index)} isotopic patterns from {file_success_count}/{file_count} file(s)"
    )
    return data


def filter_calisp_data(data, target):
    if target.lower() == "na":
        subdata = data.loc[
            lambda df: (df["flag_peak_at_minus_one_pos"] == False)
            & (df["flag_pattern_is_wobbly"] == False)
            & (df["flag_psm_has_low_confidence"] == False)
            & (df["flag_psm_is_ambiguous"] == False)
            & (df["flag_pattern_is_contaminated"] == False)
            & (df["flag_peptide_assigned_to_multiple_bins"] == False),
            :,
        ]
    elif target.lower() == "fft":
        subdata = data.loc[
            lambda df: (df["error_fft"] < 0.001)
            & (df["flag_peptide_assigned_to_multiple_bins"] == False),
            :,
        ]
    elif target.lower() == "clumpy":
        subdata = data.loc[
            lambda df: (df["error_clumpy"] < 0.001)
            & (df["flag_peptide_assigned_to_multiple_bins"] == False),
            :,
        ]

    print(
        f"{len(subdata.index)} ({len(subdata.index)/len(data.index)*100:.1f}%) remaining after filters."
    )

    return subdata


def estimate_clumpiness(data):
    subdata = data.loc[lambda df: df["error_clumpy"] < 0.001, :]
    clumpiness = []
    for c in ["c1", "c2", "c3", "c4", "c5", "c6"]:
        try:
            count, division = np.histogram(subdata[c], bins=50)
            count = count[1:-1]
            opt = 0.02 * np.where(count == count.max())[0][0] / 0.96
            clumpiness.append(opt)
        except ValueError:
            pass
    return clumpiness / sum(clumpiness)


# the function for benchmarking
def benchmark_sip_mock_community_data(data, factor):
    background_isotope = 1 - factor
    background_unlabelled = factor

    # For false positive discovery rates we set the threshold at the isotope/unlabelled associated with 1/4 of a generation
    # of labeling. The E. coli values (1.7, 4.2 and 7.1) are for 1 generation at 1, 5 and 10% label,
    # and we take the background (1.07) into account as well.
    thresholds = {
        1: 1.07 + (1.7 - 1.07) / 4,
        5: 1.07 + (4.2 - 1.07) / 4,
        10: 1.07 + (7.1 - 1.07) / 4,
    }

    filenames = data["ms_run"].unique()
    bin_names = data["bins"].unique()
    peptide_sequences = data["peptide"].unique()
    benchmarking = pd.DataFrame(
        columns=[
            "file",
            "bins",
            "% label",
            "ratio",
            "peptide",
            "psm_mz",
            "n(patterns)",
            "mean intensity",
            "ratio_NA median",
            "N mean",
            "ratio_NA SEM",
            "ratio_FFT median",
            "ratio_FFT SEM",
            "False Positive",
        ]
    )
    false_positives = 0
    for p in peptide_sequences:
        pep_data = data.loc[lambda df: df["peptide"] == p, :]
        for b in bin_names:
            bindata = data.loc[lambda df: df["bins"] == b, :]
            for f in filenames:
                words = f.split("_")
                # TODO what is nominal_value doing? it uses int(the 4th component of the filename/runname)
                # if the filename hase more than 5 components, and the nominal_value=0 otherwise
                nominal_value = 0
                if len(words) > 5:
                    nominal_value = int(words[3].replace("rep", ""))
                unlabeled_fraction = 1 - nominal_value / 100
                U = unlabeled_fraction * background_unlabelled
                I = nominal_value / 100 + unlabeled_fraction * background_isotope
                ratio = I / U * 100
                pepfiledata = pep_data.loc[lambda df: df["ms_run"] == f, :]
                is_false_positive = 0
                try:
                    if (
                        b != "K12"
                        and pepfiledata["ratio_na"].median() > thresholds[nominal_value]
                    ):
                        is_false_positive = 1
                        false_positives += 1
                except KeyError:
                    pass
                benchmarking.loc[len(benchmarking)] = [
                    f,
                    b,
                    nominal_value,
                    ratio,
                    p,
                    pepfiledata["psm_mz"].median(),
                    len(pepfiledata.index),
                    pepfiledata["pattern_total_intensity"].mean(),
                    pepfiledata["ratio_na"].median(),
                    pepfiledata["psm_neutrons"].mean(),
                    pepfiledata["ratio_na"].sem(),
                    pepfiledata["ratio_fft"].median(),
                    pepfiledata["ratio_fft"].sem(),
                    is_false_positive,
                ]

    benchmarking = benchmarking.sort_values(["bins", "peptide"])
    benchmarking = benchmarking.reset_index(drop=True)
    return benchmarking


# cleaning and filtering data
data = load_calisp_data(args.input, args.factor)
data = filter_calisp_data(data, "na")

data["peptide_clean"] = data["peptide"]
data["peptide_clean"] = data["peptide_clean"].replace("'Oxidation'", "", regex=True)
data["peptide_clean"] = data["peptide_clean"].replace("'Carbamidomethyl'", "", regex=True)
data["peptide_clean"] = data["peptide_clean"].replace("\s*\[.*\]", "", regex=True)

data["ratio_na"] = data["ratio_na"] * 100
data["ratio_fft"] = data["ratio_fft"] * 100
data["psm_neutrons"] = data["psm_neutrons"] * 100

# The column "% label" indicates the amount of label applied (percentage of label in the glucose). The amount of
# labeled E. coli cells added corresponded to 1 generation of labeling (50% of E. coli cells were labeled in
# all experiments except controls)

benchmarks = benchmark_sip_mock_community_data(data, args.factor)
benchmarks.to_csv(args.out_summary,  sep='\t', index=False)

data.to_csv(args.out_filtered,  sep='\t', index=False)
