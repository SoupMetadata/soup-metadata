import pandas as pd

def save(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False)

def load(path: str) -> pd.DataFrame:
    return pd.read_csv(path)

def merge_deadlines(df_original, df_new) -> pd.DataFrame:
    df_new_rows = df_new[(~df_new['id'].isin(df_original['id'])) & (df_new['published'] > pd.Timestamp('2026-06-01', tz='UTC'))]
    shared_cols = df_original.columns.intersection(df_new.columns)
    df_new_rows = pd.concat([df_new_rows, df_new.iloc[[-1]]])
    df_updated_deadlines = pd.concat([
        df_original.iloc[:-1], 
        df_new_rows[shared_cols]
    ], ignore_index=True)
    return df_updated_deadlines

def merge_initial(df_original, df_new) -> pd.DataFrame:
    df_new_rows = df_new[(~df_new['id'].isin(df_original['id'])) & (df_new['published'] > pd.Timestamp('2026-06-01', tz='UTC'))]
    shared_cols = df_original.columns.intersection(df_new.columns)

    df_updated_initial = pd.concat([
        df_original, 
        df_new_rows[shared_cols]
    ], ignore_index=True)
    return df_updated_initial


