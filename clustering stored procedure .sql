-- CREATE OR REPLACE PROCEDURE ECHOMIND_DB.APP.RUN_CLUSTERING(CALL_ID_INPUT VARCHAR)
-- RETURNS VARCHAR
-- LANGUAGE PYTHON
-- RUNTIME_VERSION = '3.11'
-- PACKAGES = ('snowflake-snowpark-python', 'scikit-learn', 'numpy')
-- HANDLER = 'run'
-- AS
-- $$
-- import numpy as np
-- from sklearn.cluster import KMeans
-- from sklearn.decomposition import PCA

-- def run(session, call_id_input):
--     # Get all segments with embeddings for this call
--     df = session.sql(f"""
--         SELECT SEGMENT_ID, SEGMENT_TEXT, EMBEDDING::VARCHAR AS EMB
--         FROM ECHOMIND_DB.APP.CALL_SEGMENTS
--         WHERE CALL_ID = '{call_id_input}'
--         ORDER BY START_TIME
--     """).to_pandas()

--     # Need at least 3 segments to cluster
--     if len(df) < 3:
--         return "Not enough segments to cluster"

--     # Convert embedding strings to numpy arrays
--     embeddings = np.array([eval(row) for row in df['EMB']])

--     # Pick number of clusters (3 to 5 based on segment count)
--     k = min(5, max(3, len(df) // 5))

--     # Run KMeans clustering
--     kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
--     df['CLUSTER'] = kmeans.fit_predict(embeddings)

--     # Reduce to 2D for visualization
--     pca = PCA(n_components=2)
--     coords = pca.fit_transform(embeddings)
--     df['PCA_X'] = coords[:, 0]
--     df['PCA_Y'] = coords[:, 1]

--     # Save results back to table
--     for _, row in df.iterrows():
--         session.sql(f"""
--             UPDATE ECHOMIND_DB.APP.CALL_SEGMENTS
--             SET CLUSTER_ID = {int(row['CLUSTER'])},
--                 PCA_X = {float(row['PCA_X'])},
--                 PCA_Y = {float(row['PCA_Y'])}
--             WHERE CALL_ID = '{call_id_input}'
--             AND SEGMENT_ID = {int(row['SEGMENT_ID'])}
--         """).collect()

--     return f"Done: {k} clusters assigned to {len(df)} segments"
-- $$;


CREATE OR REPLACE PROCEDURE ECHOMIND_DB.APP.RUN_CLUSTERING(CALL_ID_INPUT VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'scikit-learn', 'numpy')
HANDLER = 'run'
AS
$$
import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
import json

def run(session, call_id_input):
    df = session.sql(f"""
        SELECT SEGMENT_ID, SEGMENT_TEXT, SNOWFLAKE.CORTEX.VECTOR_TO_ARRAY(EMBEDDING) AS EMB
        FROM ECHOMIND_DB.APP.CALL_SEGMENTS
        WHERE CALL_ID = '{call_id_input}' AND EMBEDDING IS NOT NULL
        ORDER BY START_TIME
    """).to_pandas()

    if len(df) < 3:
        return "Not enough segments to cluster"

    embeddings = np.array([json.loads(row) if isinstance(row, str) else list(row) for row in df['EMB']])

    k = min(5, max(3, len(df) // 5))

    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    df['CLUSTER'] = kmeans.fit_predict(embeddings)

    pca = PCA(n_components=2)
    coords = pca.fit_transform(embeddings)
    df['PCA_X'] = coords[:, 0]
    df['PCA_Y'] = coords[:, 1]

    for _, row in df.iterrows():
        session.sql(f"""
            UPDATE ECHOMIND_DB.APP.CALL_SEGMENTS
            SET CLUSTER_ID = {int(row['CLUSTER'])},
                PCA_X = {float(row['PCA_X'])},
                PCA_Y = {float(row['PCA_Y'])}
            WHERE CALL_ID = '{call_id_input}'
            AND SEGMENT_ID = {int(row['SEGMENT_ID'])}
        """).collect()

    return f"Done: {k} clusters assigned to {len(df)} segments"
$$;


------------------------------------------------------

-- First make sure you have segments with embeddings
SELECT COUNT(*) FROM ECHOMIND_DB.APP.CALL_SEGMENTS
WHERE CALL_ID = 'YOUR_CALL_ID' AND EMBEDDING IS NOT NULL;

-- Run clustering
CALL ECHOMIND_DB.APP.RUN_CLUSTERING('YOUR_CALL_ID');

-- Check results
SELECT CLUSTER_ID, COUNT(*) AS segments, MIN(PCA_X), MAX(PCA_X)
FROM ECHOMIND_DB.APP.CALL_SEGMENTS
WHERE CALL_ID = 'YOUR_CALL_ID'
GROUP BY CLUSTER_ID
ORDER BY CLUSTER_ID;