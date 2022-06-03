"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

import MySQLdb
import re


# VARIABILI UTENTE
colonna_frase = "" # inserire il nome della colonna contenente la domanda
colonna_nome_faq = "" # inserire il nome della colonna contenente il nome della domanda
colonna_risposta = "" # inserire il nome della colonna contenente la risposta della domanda
colonna_linea = "" # inserire il nome della colonna contenente la linea relativa alla domanda
colonna_parent = "" # inserire il nome della colonna contenente l'id nella tabella sorgente



# SOURCE DATABASE
file_connessione = open("../db_connections/DB_CONNECTIONS_SOURCE.json", "r")
dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn_source = eval("MySQLdb.connect(" + dati_connessione.split(", questions_table=")[0] + ")")
file_connessione.close()
cursor_source = conn_source.cursor()
source_questions_table = dati_connessione.split("\", questions_table=\"")[1].split("\", entities_table=")[0]
source_entities_table = dati_connessione.split("\", entities_table=\"")[1].split("\", synonyms_table=")[0]
source_synonyms_table = dati_connessione.split("\", synonyms_table=\"")[1].split("\"}")[0]


# TARGET DATABASE
file_connessione = open("../db_connections/DB_CONNECTIONS.json", "r")
dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn = eval("MySQLdb.connect(" + dati_connessione + ")")
file_connessione.close()
cursor = conn.cursor()


# estrazione delle entità dal database sorgente
cursor_source.execute("SELECT entity, entity_type FROM " + source_entities_table)
array_entities = list(cursor_source.fetchall())
for ent in array_entities:
    entity = ent[0]
    entity_type = ent[1]
    cursor.execute("INSERT INTO entities (entity, entity_type) VALUES (%s, %s)", (str(entity), str(entity_type)))
    conn.commit()
conn.close()

# estrazione dei sinonimi dal database sorgente
cursor_source.execute("SELECT synonyms FROM " + source_synonyms_table)
array_synonyms = list(cursor_source.fetchall())
for synonym in array_synonyms:
    synonyms = synonym[0]
    cursor.execute("INSERT INTO synonyms (words) VALUES (%s)", (str(synonyms)))
    conn.commit()
conn.close()


# DATABASE FAQ/MANUAL
file_connessione = open("../db_connections/DB_CONNECTIONS_TABLES.json", "r")
dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn = eval("MySQLdb.connect(" + dati_connessione.split(", answers_table=")[0] + ")")
file_connessione.close()
cursor = conn.cursor()
answers_table = dati_connessione.split("\", answers_table=\"")[1].split("\", questions_table=")[0]
questions_table = dati_connessione.split("\", questions_table=\"")[1].split("\"")[0]


# estrazione delle faq
cursor_source.execute("SELECT " + colonna_frase + ", " + colonna_nome_faq + ", " + colonna_risposta + ", " + colonna_linea + ", " + colonna_parent + " FROM " + source_questions_table)
faq = list(cursor_source.fetchall())
for f in faq:
    frase = f[0].lower().strip().replace("à", "a").replace("é", "e").replace("è", "e").replace("ò", "o").replace("ì", "i").replace("ù", "u")
    frase = re.sub("[^a-zA-Z0-9 àèéìòù]+", " ", frase)
    frase = re.sub(" +", " ", frase)
    faq_title = f[1].lower().strip()
    risposta = f[2].strip().replace("\"", "'")
    linea = "\"-" + f[3].upper().strip() + "-\""
    if linea == "\"--\"":
        linea = "NULL"
    parent_id = f[4]

    cursor.execute("SELECT faq_title FROM " + answers_table + " WHERE faq_title = '" + str(faq_title) + "'")
    exist = list(cursor.fetchall())
    if len(exist) == 0:
        cursor.execute("INSERT INTO " + questions_table + " (frase, faq_title, linea, parent_id) VALUES (\"" + str(frase) + "\", \"" + str(faq_title) + "\", " + str(linea) + ", " + str(parent_id) + ")")
        conn.commit()
    
        cursor.execute("INSERT INTO " + answers_table + " (frase, faq_title, parent_id) VALUES (\"" + str(risposta) + "\", \"" + str(faq_title) + "\", " + str(parent_id) + ")")
        conn.commit()
    else:
        old_faq_title = exist[0][0]
        # Se si utilizza una sola domanda per ogni FAQ, è necessario fare l'UPDATE anche nella questions_table
        #cursor.execute("UPDATE " + questions_table + " SET frase = '" + str(frase) + "' WHERE faq_title = '" + str(old_faq_title) + "'")
        #conn.commit()
        cursor.execute("UPDATE " + answers_table + " SET frase = '" + str(frase) + "' WHERE faq_title = '" + str(old_faq_title) + "'")
        conn.commit()

conn_source.close()
conn.close()