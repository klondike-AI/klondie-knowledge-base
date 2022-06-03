"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

import re
import redis
import spacy
import MySQLdb
import subprocess
from difflib import ndiff
from datetime import datetime
from datetime import date
from datetime import timedelta
from rasa_sdk.events import SlotSet


# Caricamento del modello spaCy per l'analisi della frase
global_nlp = spacy.load("../../model/model_NER/model")

# informazioni connessione al db redis
redis_ip = ""
redis_port = ""
redis_n_db = ""

# contiene i verbi/azioni da ignorare (personalizzabile)
ignored_verbs = ["have", "be", "want", "can", "do", "like", "know", "must", "help", "interest", "need"]
# contiene i verbi/azioni che spaCy non riconosce (personalizzabile)
spacy_ignored_verbs = []
# contiene le desinenze di verbi/azioni mascherati da sostantivi (personalizzabile)
finali_verbi_sostantivi = []


# Funzione per la connessione al database che restituisce la connessione ed il cursore per le query
def db_connection():
    file_connessione = open("../../db_connections/DB_CONNECTIONS.json", "r")
    dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
    conn = eval("MySQLdb.connect(" + dati_connessione + ")")
    file_connessione.close()
    cursor = conn.cursor()

    return conn, cursor


# Funzione per la connessione al database contenente domande e risposte che restituisce la connessione ed il cursore per le query
def db_connection_tables():
    file_connessione = open("../../db_connections/DB_CONNECTIONS_TABLES.json", "r")
    dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
    conn = eval("MySQLdb.connect(" + dati_connessione.split(", answers_table=")[0] + ")")
    file_connessione.close()
    cursor = conn.cursor()
    answers_table = dati_connessione.split("\", answers_table=\"")[1].split("\", questions_table=")[0]
    questions_table = dati_connessione.split("\", questions_table=\"")[1].split("\"")[0]

    return conn, cursor, answers_table, questions_table


# Funzione per salvare l'ultima interazione dell'utente con il bot
def db_connection_last_interaction():
    file_connessione = open("../../db_connections/DB_CONNECTIONS_LAST_INTERACTION.json", "r")
    dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
    conn = eval("MySQLdb.connect(" + dati_connessione.split(", table_last_interaction=")[0] + ")")
    file_connessione.close()
    cursor = conn.cursor()
    table_last_interaction = dati_connessione.split("\", table_last_interaction=\"")[1].split("\", foldername_last_interaction=")[0]
    foldername_last_interaction = dati_connessione.split("\", foldername_last_interaction=\"")[1].split("\", field_last_interaction=")[0]
    field_last_interaction = dati_connessione.split("\", field_last_interaction=\"")[1].split("\"")[0]

    current_date = datetime.now() + timedelta(hours=1)
    bot_name = str(subprocess.check_output("pwd", shell=True)).split("/")[4] #/home/jovyan/work/<nome>
    cursor.execute("UPDATE " + table_last_interaction + " SET " + field_last_interaction + " = \"" + current_date.strftime("%Y-%m-%d %H:%M:%S") + "\" WHERE " + foldername_last_interaction + " = \"" + bot_name + "\"")
    conn.commit()
    conn.close()

    return



# Funzione per salvare le emoji codificate nel db, ma non gli accenti
def encode_emoji(message):
    encoded = str(message.encode('unicode-escape'))[2:-1]
    encoded = encoded.replace("\\\\U", "???U")
    message_without_emoji = eval('"' + encoded.replace('"', "\\\"").replace("\\\\", "\\") + '"')
    message_without_emoji = message_without_emoji.replace("???U", "\\\\U")

    return message_without_emoji



# Funzione per salvare la conversazione con il chatbot
def save_conversation(tracker, result, update=0):
    conn, cursor = db_connection()

    if len(result) > 0:
        result = "'" + result + "'"
    else:
        result = "NULL"

    events = ""
    messages = ""
    last_timestamp = datetime.now() + timedelta(hours=1)
    # si scrive l'ultima conversazione nella tabella "conversations" dal messaggio "Come posso aiutarti?"
    for e in list(tracker.events):
        events = events + str(e) + ";;;"

        # si riporta chi ha scritto ciascun messaggio
        user = ""
        if "'event': " in str(e) and e['event'] is not None:
            user = str(e['event']).upper() + ": "
        # si riporta il testo di ciascun messaggio
        if "'text': " in str(e) and e['text'] is not None:
            if e['text'] == "How can I help you?" or "\nHow can I help you?" in e['text']:
                messages = user + e['text'] + ";;;"
                events = str(e) + ";;;"
            else:
                messages = messages + user + e['text'] + ";;;"

    messages = encode_emoji(messages)
    messages = messages.replace(";;;", "\n\n").strip()
    events = encode_emoji(events)
    events = events.replace(";;;", "\n\n").strip()

    if update == 1:
        cursor.execute("UPDATE conversations SET messages = \"" + messages.replace("\"", "'") + "\", last_timestamp = \""+ str(last_timestamp) + "\", events = \"" + events.replace("\"", "'") + "\", result = " + str(result) + ", sender_id = '" + str(tracker.sender_id) + "' WHERE sender_id LIKE '" + str(tracker.sender_id) + "' ORDER BY last_timestamp DESC LIMIT 1")
    else:
        cursor.execute("INSERT INTO conversations (messages, last_timestamp, events, result, sender_id) VALUES (\"" + messages.replace("\"", "'") + "\", \""+ str(last_timestamp) + "\", \"" + events.replace("\"", "'") + "\", " + str(result) + ", '" + str(tracker.sender_id) + "')")
    conn.commit()
    conn.close()
    return


# Funzione per salvare la conversazione con il chatbot che è finita in Fallback
def save_fallback_conversation(tracker, message):
    conn, cursor = db_connection()
    
    events = ""
    messages = ""
    last_timestamp = datetime.now() + timedelta(hours=1)
    # si scrive l'ultima conversazione nella tabella "conversations" dal messaggio "Come posso aiutarti?"
    for e in list(tracker.events):
        events = events + str(e) + ";;;"

        # si riporta chi ha scritto ciascun messaggio
        user = ""
        if "'event': " in str(e) and e['event'] is not None:
            user = str(e['event']).upper() + ": "
        # si riporta il testo di ciascun messaggio
        if "'text': " in str(e) and e['text'] is not None:
            if e['text'] == "How can I help you?" or "\nHow can I help you?" in e['text']:
                messages = user + e['text'] + ";;;"
                events = str(e) + ";;;"
            else:
                messages = messages + user + e['text'] + ";;;"
    messages = messages + "BOT: " + message + ";;;"

    messages = encode_emoji(messages)
    messages = messages.replace(";;;", "\n\n").strip()
    events = encode_emoji(events)
    events = events.replace(";;;", "\n\n").strip()

    cursor.execute("INSERT INTO fallback_events (last_message, last_timestamp, events, sender_id) VALUES (\"" + messages.replace("\"", "'") + "\", \"" + str(last_timestamp) + "\", \"" + events.replace("\"", "'") + "\", '" + str(tracker.sender_id) + "')")
    conn.commit()
    conn.close()
    return


# estrae il contenuto delle variabili globali dagli slot
# riceve un array di nomi degli slot e il tracker per leggerli; ritorna il contenuto degli slot in un array
def global_variables(slots_name, tracker):
    # slot che devono essere inizializzati con una stringa vuota
    slots_empty_string = ["filter_string", "root", "faq_title_finale", "email_slot", "query_more_rows"]
    # slot che devono essere inizializzati con una lista vuota
    slots_empty_list = ["action_only_action", "entity_type_only_action", "entity_only_action"]
    # slot che devono essere inizializzati con zero
    slots_zeros = ["only_action", "more_rows", "check_more_entities"]

    slots_content = []
    for name in slots_name:
        value = tracker.get_slot(name)
        if value is None:
            if name in slots_empty_list:
                slots_content.append([])
            elif name in slots_empty_string:
                slots_content.append("")
            else:
                slots_content.append(0)
        else:
            slots_content.append(value)

    if len(slots_content) == 1:
        return slots_content[0]
    else:
        return slots_content


# aggiorna il contenuto degli slot che rappresentano le variabili globali
def update_global_variables(slots_names, values_list):
    slots_set = []
    for ct, name in enumerate(slots_names):
        slots_set.append(SlotSet(name, values_list[ct]))
    return slots_set


# Funzione che estrae la query con i lemmi delle entità al posto delle entità
def query_entities_lemma(faq_title, query_more_rows, entita):
    global global_nlp
    conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
    new_faq_title = faq_title
    new_query_more_rows = query_more_rows

    # query su entities_lemma con i le entità trovate
    if len(faq_title) == 0:
        # query sui lemmi
        query_more_rows_lemma = query_more_rows
        query_more_rows_lemma = query_more_rows_lemma.replace("entities REGEXP", "entities_lemma REGEXP")
        query_more_rows_lemma = query_more_rows_lemma.replace("faq_title, entities, id", "faq_title, entities_lemma, id")

        cursor_tables.execute(query_more_rows_lemma)
        faq_title_lemma = cursor_tables.fetchall()

        if len(faq_title_lemma) != 0:
            new_faq_title = faq_title_lemma
            new_query_more_rows = query_more_rows_lemma
    
    # query su entities_lemma con i lemmi delle entità trovate
    if len(new_faq_title) == 0:
        # query sui lemmi
        query_more_rows_lemma = query_more_rows
        query_more_rows_lemma = query_more_rows_lemma.replace("entities REGEXP", "entities_lemma REGEXP")
        query_more_rows_lemma = query_more_rows_lemma.replace("faq_title, entities, id", "faq_title, entities_lemma, id")

        for e in entita:
            entity_lemma = ""
            doc_ent = global_nlp(e.strip())
            for e1 in doc_ent:
                entity_lemma = entity_lemma + str(e1.lemma_) + " "
            query_more_rows_lemma = query_more_rows_lemma.replace("'" + e + "'", "'" + entity_lemma.strip() + "'")

        cursor_tables.execute(query_more_rows_lemma)
        faq_title_lemma = cursor_tables.fetchall()

        if len(faq_title_lemma) != 0:
            new_faq_title = faq_title_lemma
            new_query_more_rows = query_more_rows_lemma
    conn_tables.close()
    
    return new_faq_title, new_query_more_rows



# ritorna tutte le entità ed i tipi utilizzati, presenti nella tabella "faq_questions"
def get_entities(cursor, conn_tables, cursor_tables, questions_table, filter_string, get_spacy_entities=False):
    cursor_tables.execute("SELECT DISTINCT entities FROM " + questions_table + filter_string.replace("AND", "WHERE"))
    entities = list(cursor_tables.fetchall())
    entity_set = set()
    types_set = set()
    spacy_entities = {}
    # le prendo tutte e guarda in ActionRetrieveFaq se compare nella tripla
    for ent in entities: 
        e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
        if e["entities"].lower() != "none":
            for e1 in eval(e["entities"]):
                cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e1['entity'] + "'%\"")
                sinonimi = list(cursor.fetchall())
                if len(sinonimi) > 0:
                    sinonimi = sinonimi[0][0]
                    for s in eval(sinonimi):
                        entity = str(s).lower()
                        types_set.add(str(e1["entity_type"]).lower())
                        spacy_entities[entity] = str(e1["entity_type"]).lower() # dizionario {entita:tipo}
                        entity_set.add(str(s).lower())
                else:
                    entity = str(e1["entity"]).lower()
                    types_set.add(e1["entity_type"].lower())
                    spacy_entities[entity] = str(e1["entity_type"]).lower() # dizionario {entita:tipo}
                    entity_set.add(e1["entity"].lower())

    if get_spacy_entities:
        return types_set, entity_set, spacy_entities
    else:
        return types_set, entity_set



# ritorna tutti i lemmi delle entità utilizzate, presenti nella tabella "faq_questions"
def get_entities_lemma(cursor, conn_tables, cursor_tables, questions_table, filter_string, get_spacy_entities=False):
    cursor_tables.execute("SELECT DISTINCT entities_lemma FROM " + questions_table + filter_string.replace("AND", "WHERE"))
    entita_lemma = list(cursor_tables.fetchall())
    entities_lemma = set()
    spacy_entities = {}
    for ent in entita_lemma:
        e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
        if e["entities"].lower() != "none":
            for e1 in eval(e["entities"]):
                cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e1['entity'] + "'%\"")
                sinonimi = list(cursor.fetchall())
                if len(sinonimi) > 0:
                    sinonimi = sinonimi[0][0]
                    for s in eval(sinonimi):
                        entity = str(s).lower()
                        spacy_entities[entity] = str(e1["entity_type"]).lower() # dizionario {entita:tipo}
                        entities_lemma.add(entity) # array con tutte le entita usato sotto
                else:
                    entity = str(e1["entity"]).lower()
                    spacy_entities[entity] = str(e1["entity_type"]).lower() # dizionario {entita:tipo}
                    entities_lemma.add(entity) # array con tutte le entita usato sotto

    if get_spacy_entities:
        return entities_lemma, spacy_entities
    else:
        return entities_lemma



# Funzione per l'estrazione di tutti i sinonimi di un "element", ritornati in un set
def get_synonyms(cursor, element):
    element_synonyms = set()
    cursor.execute("SELECT words FROM synonyms")
    synonyms = list(cursor.fetchall())
    for s in synonyms:
        sinonimi = eval(s[0])
        if element in sinonimi:
            for s1 in sinonimi:
                element_synonyms.add(s1)
    return element_synonyms



# The Levenshtein distance is a string metric for measuring the difference between two sequences.
# It is calculated as the minimum number of single-character edits necessary to transform one string into another
def calculate_levenshtein_distance(str_1, str_2):
    distance = 0
    buffer_removed = buffer_added = 0
    for x in ndiff(str_1, str_2):
        code = x[0]
        # Code ? is ignored as it does not translate to any modification
        if code == ' ':
            distance += max(buffer_removed, buffer_added)
            buffer_removed = buffer_added = 0
        elif code == '-':
            buffer_removed += 1
        elif code == '+':
            buffer_added += 1
    distance += max(buffer_removed, buffer_added)
    return distance



# crea le condizioni in OR nelle query mettendo le combinazioni dei vari sinonimi delle entità ricevute come parametro
def trova_sinonimi_entita(condition, entita):
    conn, cursor = db_connection()
    
    all_condition = [condition]
    for e in entita:
        cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e + "'%\"")
        words = cursor.fetchall()
        if len(words) != 0:
            sinonimi = eval(words[0][0])
            for s in sinonimi:
                alternativa = condition.replace("'" + e + "'", "'" + s + "'")
                if alternativa not in all_condition:
                    all_condition.append(alternativa)
                    if len(entita) > 1:
                        for e1 in entita[1:]:
                            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e1 + "'%\"")
                            words1 = cursor.fetchall()
                            if len(words1) != 0:
                                sinonimi1 = eval(words1[0][0])
                                for s1 in sinonimi1:
                                    alternativa1 = condition.replace("'" + e1 + "'", "'" + s1 + "'")
                                    if alternativa1 not in all_condition:
                                        all_condition.append(alternativa1)
    conn.close()
    return all_condition



# cerca se una parola è contenuta in una frase, ma non è contenuta in altre parole
def findWholeWord(w):
    return re.compile(r'\b({0})\b'.format(w), flags=re.IGNORECASE).search



# data una frase in input, ritorna il dizionario di azione ed entità in essa contenute
def json_generator(frase, tracker):
    root, filter_string = global_variables(["root", "filter_string"], tracker)
    global global_nlp
    nlp = global_nlp
    
    conn, cursor = db_connection()
    conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
    
    # prende tutte le {entita:tipo} più i relativi sinonimi (e lemmi)
    dict_spacy_entities = {}
    types_set, entity_set, spacy_entities = get_entities(cursor, conn_tables, cursor_tables, questions_table, filter_string, True)
    entity_set_lemma, spacy_entities_lemma = get_entities_lemma(cursor, conn_tables, cursor_tables, questions_table, filter_string, True)
    spacy_entities.update(spacy_entities_lemma)
    for e in entity_set:
        dict_spacy_entities[e] = "entity"
    for e in entity_set_lemma:
        dict_spacy_entities[e] = "lemma"
    
    # verbi che devono essere ignorati (a meno che non siano gli unici nella frase)
    global ignored_verbs
    # verbi che spaCy non riconosce
    global spacy_ignored_verbs
    # processore di linguaggio naturale (spaCy)
    doc = nlp(frase.lower())
    # json iniziale che conterrà l'intento e le eventuali entità della frase (con i relativi tipi)
    json = {"action": "None", "entities": "None"}
    # variabile per memorizzare il verbo "root" estratto dalla frase
    root = ""
    # indica se la root estratta da spaCy è valida
    found_action = False    
    # queste due variabili indicano se la frase contiene i verbi ausiliari
    contains_essere = False
    contains_avere = False
    # indica se esiste un verbo nella frase spaCy (diverso da "essere"/"avere")
    contains_verb = False
    # se trova un verbo da ignorare lo salva perché viene usato come root se non ce ne sono altri
    ignore_verb = ""
    contains_ignore_verb = False
    # se trova un "verbo mascherato in un sostantivo" (es. annullamento) lo estrae perché viene usato come root se non ce ne sono altri
    contains_verbo_sostantivo = False
    verbo_sostantivo = ""
    # variabile che indica se la frase conteneva almeno un verbo
    no_action = False
    
    # Se la root estratta da spaCy È un verbo, si prende quella
    for t in doc:
        # Se la root estratta da spaCy È un verbo, si prende quella
        if t.dep_ == "ROOT" and (t.pos_ == "VERB" or t.pos_ == "AUX") and t.lemma_.lower() not in ignored_verbs:
            found_action = True
            contains_verb = True
            json["action"] = t.lemma_.lower()
                
        # Se la root estratta da spaCy NON È un verbo, ma nella frase è presente un verbo, si prende quello
        elif (t.pos_ == "VERB" or t.pos_ == "AUX") and found_action == False and t.lemma_.lower() not in ignored_verbs:
            json["action"] = t.lemma_.lower()
            contains_verb = True

        # si riporta se la frase contiene un verbo ausiliario, utilizzando la relativa variabile booleana
        if t.lemma_.lower() == "be":
            contains_essere = True
        if t.lemma_.lower() == "have":
            contains_avere = True

        # Se la root estratta da spaCy NON È un verbo e non trova altri verbi neanche con i pronomi, si tiene un verbo da ignorare (se presente)
        # IGNORE_VERB
        if (t.pos_ == "VERB" or t.pos_ == "AUX") and contains_verb == False and t.lemma_.lower() in ignored_verbs:
            ignore_verb = t.lemma_.lower()
            contains_ignore_verb = True
            if ignore_verb == "be" or ignore_verb == "have":
                ignore_verb = "have information"
        # Se la root estratta da spaCy NON È un verbo e non trova altri verbi neanche con i pronomi, si tiene uno dei verbi che spaCy non rileva (se presente)
        # VERBI NON RILEVATI DA SPACY
        elif contains_verb == False and t.pos_ != "VERB" and t.lemma_.lower() in spacy_ignored_verbs:
            ignore_verb = t.lemma_.lower()
            contains_ignore_verb = True
        # Se la root estratta da spaCy NON È un verbo e non trova altri verbi neanche con i pronomi, si tiene uno dei verbi mascherati da sostantivi (se presente)
        # VERBI MASCHERATI DA SOSTANTIVI
        else:
            for f in finali_verbi_sostantivi:
                if f == str(t.text)[-(len(f)):] and f != t.text:
                    contains_verbo_sostantivo = True
                    verbo_sostantivo = str(t.text).replace(f, "")

    # Se spaCy non rileva verbi, ma è presente il verbo "essere", si prende quello
    if contains_verb == False and contains_essere == True:
        root = "have information"
    # Se spaCy non rileva verbi, non è presente il verbo "essere" ma è presente il verbo "avere", si prende quello
    elif contains_verb == False and contains_essere == False and contains_avere == True:
        root = "have information"
    # Se spaCy non rileva verbi e trova solo "ignore_verb", lo utilizza come root
    if contains_verb == False and contains_ignore_verb == True:
        json["action"] = ignore_verb
    # Se spaCy non rileva verbi e trova solo un verbo mascherato da sostantivo, lo utilizza come root
    elif contains_verb == False and contains_verbo_sostantivo == True:
        json["action"] = verbo_sostantivo
    # Se spaCy non rileva nessuna tipologia di verbo, utilizza come root "avere informazioni"
    elif contains_verb == False and contains_ignore_verb == False:
        json["action"] = "have information"
        
    # Se nella frase è presente solamente il verbo "avere" oppure il verbo "essere", si utilizza come intento "avere informazioni"
    if json["action"] == "None" and root == "have information":
        json["action"] = "have information"
    # Se nella frase non è presente alcun verbo, si utilizza di default l'intento "avere informazioni"
    elif json["action"] == "None":
        json["action"] = "have information"
        no_action = True
    
    # aggiunge eventuali entità composte da più parole
    domanda = re.sub("[^a-zA-Z0-9 àèéìòù]+", " ", frase)
    domanda = re.sub(" +", " ", domanda)

    # frase composta dai lemmi
    frase_lemma = ""
    doc_domanda = nlp(domanda.lower().strip())
    for d in doc_domanda:
        frase_lemma = frase_lemma + d.lemma_ + " "

    entities = []
    for s in spacy_entities:
        # estrazione e pulizia del tipo
        tipo = str(spacy_entities[s]).lower()
        tipo = re.sub('[^a-zA-Z0-9 àèéìòù]+', ' ', tipo)
        # estrazione e pulizia dell'entità
        entita = str(s).lower()
        entita = re.sub('[^a-zA-Z0-9 àèéìòù]+', ' ', entita)

        # si cercano le entità nella frase semplice
        new_entity = "{'entity_type': '" + tipo + "', 'entity': '" + entita + "'}"
        if findWholeWord(str(s))(domanda.strip().lower()) != None and new_entity not in entities:
            entities.append(new_entity)
        # se l'entità è un lemma, si cerca l'entità nella frase composta dai lemmi di ciascuna parola
        elif dict_spacy_entities[str(s)] == "lemma" and findWholeWord(str(s))(frase_lemma.strip().lower()) != None:
            entita_lemma = str(s)
            # si estrae dalla frase l'entità senza lemma e si salva con il relativo tipo
            entita = ""
            first_pos = len(frase_lemma.split(entita_lemma)[0].split(" ")) - 1
            for i in range(first_pos, first_pos + len(entita_lemma.split(" "))):
                entita = entita + domanda.split(" ")[i] + " "
            entita = entita.strip()
            new_entity = "{'entity_type': '" + tipo + "', 'entity': '" + entita + "'}"
            if new_entity not in entities:
                entities.append(new_entity)
    
    # Si vogliono togliere le entità contenute in altre presenti nella frase
    entities_temp = []
    for e in entities:
        # si aggiunge all'inizio dell'entità il numero di parole che la compongono
        n_words = len(eval(e)["entity"].split(" "))
        if n_words > 9:
            n_words = 9
        entities_temp.append(str(n_words) + str(e))
    # si ordinano le entità in base al numero di parole che la compongono
    entities_temp.sort(reverse=True)

    # si estraggono le entità contenute in altre, dovranno essere escluse
    excluded_entities = []
    for e in entities_temp:
        if e not in excluded_entities:
            words = eval(e[1:])["entity"].split(" ")
            for e1 in entities_temp:
                if e != e1:
                    words1 = eval(e1[1:])["entity"].split(" ")
                    for w in words:
                        if w in words1:
                            excluded_entities.append(e1) # popola con le entita da ignorare

    # mette in entities solo le entita da non ignorare
    entities = []
    for e in entities_temp:
        if e not in excluded_entities:
            entities.append(e[1:])

    # le entità vengono ordinate
    json["entities"] = "[]"
    entities.sort()
    if str(entities) != "[]":
        json["entities"] = str(entities).replace('"{', '{').replace('}"', '}')

    conn.close()
    conn_tables.close()
    return json, no_action



# funzione che svuota gli slot Redis al termine di una conversazione tra operatore e utente
def fine_conversazione(timer, tracker):
    db_connection_last_interaction()
    global redis_ip
    global redis_port
    global redis_n_db
    
    # rimuove l'utente anche dal database 0
    redis_db = redis.Redis(host=redis_ip, port=redis_port, db=0, decode_responses=True)
    redis_db.delete(str(tracker.sender_id))
    redis_db = redis.Redis(host=redis_ip, port=redis_port, db=redis_n_db, decode_responses=True)
    message_number_operatore = redis_db.get("OPERATORE:" + str(tracker.sender_id))
    if timer == True: # controlla se era scaduto il timer (cioè se timer è True)
        if message_number_operatore == "0": #controlla se l'operatore si era connesso
            message = "We apologize but there is currently no operator available.  \nYou will be contacted at the email address provided as soon as possible."
        else:
            message = "We apologize but the operator is no longer available, you can try again later."
    else:
        message = "The chat with our operator is over."

    # eliminazione delle entry di questo utente nel database redis
    clienti = eval(redis_db.get("CLIENTI"))
    clienti.remove(tracker.sender_id)
    redis_db.set("CLIENTI", str(clienti))
    if len(clienti) == 0:
        redis_db.flushdb()
    else:
        messages_number = eval(redis_db.get("CLIENTE:" + str(tracker.sender_id)))[1]
        for i in range(0, messages_number + 1):
            redis_db.delete("CLIENTE:" + str(tracker.sender_id) + ":" + str(i))
        messages_number_operatore = int(redis_db.get("OPERATORE:" + str(tracker.sender_id)))
        for i in range(0, messages_number_operatore + 1):
            redis_db.delete("OPERATORE:" + str(tracker.sender_id) + ":" + str(i))
            
        redis_db.delete("CLIENTE:" + str(tracker.sender_id))
        redis_db.delete("STORIA:" + str(tracker.sender_id))
        redis_db.delete("OPERATORE:" + str(tracker.sender_id))
        redis_db.delete("LAST_READ_OPERATORE:" + str(tracker.sender_id))
        redis_db.delete("TIMESTAMP:" + str(tracker.sender_id))

    return message


# funzione che svuota gli slot Rasa al termine di una conversazione tra operatore e utente
def exit_after_operator(tracker):
    db_connection_last_interaction()
    conn, cursor = db_connection()
    conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
    
    # estrazione global variables
    root, action_only_action, entity_type_only_action, entity_only_action, only_action = global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], tracker)
    
    assertion = tracker.get_slot("assertion")
    
    # se il bot non ha saputo rispondere correttamente all'utente, salva conversazione con "result"="no"
    if assertion == "no":
        # salvataggio della conversazione
        save_conversation(tracker, "no")
        
    # se il bot ha saputo rispondere correttamente all'utente, salva conversazione con "result"="si"
    else:
        # salvataggio della conversazione
        save_conversation(tracker, "sì")
    
    conn.close()
    conn_tables.close()
    message = "How can I help you?"
    return message
