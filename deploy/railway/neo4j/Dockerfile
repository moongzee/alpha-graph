# Railway용 Neo4j
FROM neo4j:5.21

# 메모리 절약(Railway Hobby 기준). 운영 시 상향.
ENV NEO4J_server_memory_heap_initial__size=256m
ENV NEO4J_server_memory_heap_max__size=512m
ENV NEO4J_server_memory_pagecache_size=256m

# APOC 플러그인
ENV NEO4J_PLUGINS='["apoc"]'

# 7474=HTTP(브라우저), 7687=Bolt(드라이버)
EXPOSE 7474 7687
