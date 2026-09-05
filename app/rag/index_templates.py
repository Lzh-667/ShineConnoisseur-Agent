"""movie_vec / review_vec 索引 mapping 定义。

文本字段与后端 movie/review 索引保持一致的 IK 分词与加权结构（保证 RRF 两路质量均衡）；
content_embedding 为 BGE-M3 1024 维向量（cosine + HNSW）。
"""

_DENSE_VECTOR = {
    "type": "dense_vector",
    "dims": 1024,
    "index": True,
    "similarity": "cosine",
    "index_options": {"type": "hnsw", "m": 16, "ef_construction": 100},
}

_TEXT_IK = {"type": "text", "analyzer": "ik_max_word", "search_analyzer": "ik_smart"}

MOVIE_VEC_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "long"},
            "title": _TEXT_IK,
            "originalTitle": _TEXT_IK,
            "director": _TEXT_IK,
            "actors": _TEXT_IK,
            "genre": {"type": "keyword"},
            "region": {"type": "keyword"},
            "summary": _TEXT_IK,
            "status": {"type": "integer"},
            "content_embedding": _DENSE_VECTOR,
        }
    },
}

REVIEW_VEC_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "long"},
            "title": _TEXT_IK,
            "content": _TEXT_IK,
            "movieId": {"type": "long"},
            "movieTitle": _TEXT_IK,
            "spoiler": {"type": "integer"},
            "status": {"type": "integer"},
            "content_embedding": _DENSE_VECTOR,
        }
    },
}
