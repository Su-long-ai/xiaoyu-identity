# -*- coding: utf-8 -*-
from eval_gap_hybrid_bge_exposed16_cached import (
    LocalBGE, verify_frozen_ranker, pool_docs, ensure_embeddings
)
def main():
    model=LocalBGE()
    binding=verify_frozen_ranker()
    for persona in ("Martin_Keller","Dr._Elena_Markovic"):
        docs=pool_docs(persona)
        ensure_embeddings(model,persona,docs,binding)
if __name__=="__main__":main()
