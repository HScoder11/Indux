import pandas as pd
df = pd.read_csv("data/benchmark/ims/ims_features.csv", parse_dates=["time"])
late = df[df.time >= "2004-02-16 02:42"]
print(late.groupby("bearing")[["env_bpfo_snr", "kurtosis", "rms"]].median().round(2))