"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

import MySQLdb
import sys
import os
import re

def findWholeWord(w):
    return re.compile(r'\b({0})\b'.format(w), flags=re.IGNORECASE).search

###############################
##### RETRAIN DI SPACY ########
###############################
## Generazione dei file
file_connessione = open("../../db_connections/DB_CONNECTIONS.json", "r")
dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn = eval("MySQLdb.connect(" + dati_connessione + ")")
file_connessione.close()
cursor = conn.cursor()

file_connessione = open("../../db_connections/DB_CONNECTIONS_TABLES.json", "r")
dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn_tables = eval("MySQLdb.connect(" + dati_connessione.split(", answers_table=")[0] + ")")
file_connessione.close()
cursor_tables = conn_tables.cursor()
answers_table = dati_connessione.split("\", answers_table=\"")[1].split("\", questions_table=")[0]
questions_table = dati_connessione.split("\", questions_table=\"")[1].split("\"")[0]



## Aggiunge le frasi verificate dall'utente (con entità) al training set di spacy (se non già presenti)
cursor_tables.execute("SELECT frase, entities FROM " + questions_table + " WHERE entities LIKE \"%[{%\"")
faq_questions = list(cursor_tables.fetchall())

# Elimina tutte le righe in "spacy_sentences". Si può rimuovere nel caso in cui si vogliano solo aggiungere le righe nuove
cursor.execute("DELETE FROM spacy_sentences")
conn.commit()

cursor.execute("SELECT frase FROM spacy_sentences")
spacy_sentences = list(cursor.fetchall())

for faq in faq_questions:
    # se non esiste la frase si inserisce la coppia (frase, entità)
    faq_in_spacy_sentences = False
    for s in spacy_sentences:
        if faq[0] in s:
            faq_in_spacy_sentences = True
            break

    # se la frase contiene entità che sono SUBSTRING di altre, vengono rimosse (es. "fatture" e "fatture avanzate")
    entities_list = eval(faq[1].replace("'[", "[").replace("]'", "]"))['entities']
    entities = entities_list.copy()
    for ent in entities_list:
        for ent1 in entities_list:
            if findWholeWord(ent1['entity'])(ent['entity']) != None and ent1['entity'] != ent['entity']:
                if ent1 in entities:
                    entities.remove(ent1)
     
    # se la frase non è presente nella tabella spacy_sentences si aggiunge alla tabella
    if faq_in_spacy_sentences == False:
        spacy_entities = "["
        for e in entities:
            if len(spacy_entities) > 1:
                spacy_entities = spacy_entities + ", "
            start = findWholeWord(e['entity'])(faq[0].lower()).start()
            end = findWholeWord(e['entity'])(faq[0].lower()).end()
            spacy_entities = spacy_entities + "(" + str(start) + ", " + str(end) + ", '" + e['entity_type'].upper() + "')"
        spacy_entities = spacy_entities + "]"
        cursor.execute("INSERT INTO spacy_sentences (frase, entities) VALUES (%s, %s)", (str(faq[0]), str(spacy_entities)))
        conn.commit()
        
    # se esiste già la frase nel DB, si aggiornano le entità
    else:
        spacy_entities = "["
        for e in entities:
            if len(spacy_entities) > 1:
                spacy_entities = spacy_entities + ", "
            start = findWholeWord(e['entity'])(faq[0].lower()).start()
            end = findWholeWord(e['entity'])(faq[0].lower()).end()
            spacy_entities = spacy_entities + "(" + str(start) + ", " + str(end) + ", '" + e['entity_type'].upper() + "')"
        spacy_entities = spacy_entities + "]"
        cursor.execute("UPDATE spacy_sentences SET entities = \"" + str(spacy_entities) + "\" WHERE frase = \"" + faq[0] + "\"")
        conn.commit()



## Retrain di spaCy
cursor.execute("SELECT frase, entities FROM spacy_sentences")
sentences = list(cursor.fetchall())

# preparazione della stringa per il file di training di spaCy
train_ner = ""
for s in sentences:
    frase = s[0]
    frase = frase.replace("à", "a").replace("é", "e").replace("è", "e").replace("ì", "i").replace("ò", "o").replace("ù", "u")
    frase = re.sub('[^0-9a-zA-Z\- ]+', ' ', frase)
    entities = s[1]
    train_ner = train_ner + "(\"" + str(frase) + "\", {\"entities\": " + str(entities) + "}),\n"
train_ner = train_ner[:-2]

f = open("../../model/model_NER/train_ner.txt", "w")
f.write(str(train_ner))
f.close()

# Avvio retrain in background
filename = "../../model/model_NER/train_ner.py"
os.system("python " + filename + " &")
conn.close()
conn_tables.close()