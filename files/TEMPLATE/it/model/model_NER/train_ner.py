"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

from __future__ import unicode_literals, print_function

import plac
import random
from pathlib import Path
import spacy
from spacy.util import minibatch, compounding
import MySQLdb
import sys
import time


@plac.annotations(
    output_dir=("Optional output directory", "option", "o", Path),
    n_iter=("Number of training iterations", "option", "n", int),
)
def main(output_dir="../../model/model_NER/model/", n_iter=200):
    #spacy.prefer_gpu()
    nlp = spacy.load("../../standard_model_it/it_core_news_md/it_core_news_md-2.3.0")

    # create the built-in pipeline components and add them to the pipeline
    # nlp.create_pipe works for built-ins that are registered with spaCy
    if "ner" not in nlp.pipe_names:
        ner = nlp.create_pipe("ner")
        nlp.add_pipe(ner, last=True)
    # otherwise, get it so we can add labels
    else:
        ner = nlp.get_pipe("ner")
    
    file = open("../../model/model_NER/train_ner.txt", "r") # DA AGGIORNARE IN BASE A DOVE SI AVVIA
    TRAIN_DATA = eval("[" + file.read() + "]")
    file.close()

    # add labels
    for _, annotations in TRAIN_DATA:
        for ent in annotations.get("entities"):
            ner.add_label(ent[2])

    # get names of other pipes to disable them during training
    pipe_exceptions = ["ner", "trf_wordpiecer", "trf_tok2vec"]
    other_pipes = [pipe for pipe in nlp.pipe_names if pipe not in pipe_exceptions]
    with nlp.disable_pipes(*other_pipes):  # only train NER
        # reset and initialize the weights randomly – but only if we're
        # training a new model
        for itn in range(n_iter):
           # print("Iterazione ", itn+1 , " di ", n_iter)
            random.shuffle(TRAIN_DATA)
            losses = {}
            # batch up the examples using spaCy's minibatch
            batches = minibatch(TRAIN_DATA, size=compounding(4.0, 32.0, 1.001))
            for batch in batches:
                texts, annotations = zip(*batch)
                nlp.update(
                    texts,  # batch of texts
                    annotations,  # batch of annotations
                    drop=0.5,  # dropout - make it harder to memorise data
                    losses=losses,
                )
                
    if output_dir is not None:
        output_dir = Path(output_dir)
        if not output_dir.exists():
            output_dir.mkdir()
        nlp.to_disk(output_dir)
        
    file_connessione = open("../../db_connections/DB_CONNECTIONS.json", "r")
    dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
    conn = eval("MySQLdb.connect(" + dati_connessione + ")")
    file_connessione.close()
    cursor = conn.cursor()
    
    # Aggiornamento della colonna "spacy_train_complete" per avvisare che il train di spacy è terminato
    time.sleep(1)
    cursor.execute("UPDATE rasa_faq_models SET spacy_train_complete = 'True' ORDER BY id DESC LIMIT 1")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
