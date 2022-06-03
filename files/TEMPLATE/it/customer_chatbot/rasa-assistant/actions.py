"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.forms import FormAction
from rasa_sdk.events import Restarted
from rasa_sdk.events import FollowupAction
from rasa_sdk.events import UserUtteranceReverted
from rasa_sdk.executor import CollectingDispatcher
import re
import redis
import spacy
import MySQLdb
import subprocess
from typing import Any, Text, Dict, List, Union
# per ritornare data, ora e giorno della settimana
import time
import calendar
from pytz import timezone
from datetime import date
from datetime import datetime
from datetime import timedelta
# Libreria interna
from Utils import *


# Caricamento del modello spaCy per l'analisi della frase
global_nlp = spacy.load("../../model/model_NER/model")

# informazioni connessione al db redis
redis_ip = ""
redis_port = ""
redis_n_db = ""

min_similarity_fallback = 0.9

# contiene i verbi/azioni da ignorare (personalizzabile)
ignored_verbs = ["avere", "essere", "volere", "potere", "riuscire", "fare", "piacere", "sapere", "dovere", "interessare", "aiutare", "servire"]


##################################################
##### Variabili globali gestite con gli slot #####
##################################################
### Slot per memorizzare la root di una frase
# - root

### Slot che contiene le informazioni di interesse se il primo messaggio contiene solamente: azione, tipo o entità
# - action_only_action
# - entity_type_only_action
# - entity_only_action
# - only_action

### Slot per gestire la presenza di più entità all'interno di una frase
# - check_more_entities

### Se la frase è riconducibile a più faq, la variabile viene settata al numero totale di faq proposte all'utente
# - more_rows

### Lista di tutte le faq riconducibili alla frase iniziale, da proporre all'utente
# - query_more_rows


# Quando viene avviato il chatbot, si salva il timestamp
db_connection_last_interaction()
    


# Estrae eventuali filtri da applicare alle faq
class ActionExtractFilter(Action):

    def name(self):
        return "action_extract_filter"

    def run(self, dispatcher, tracker, domain):
        message = tracker.latest_message['text']
        filter_string = global_variables(["filter_string"], tracker)
        if filter_string == "":
            if '#' in message and len(message.split('#')[1].strip()) > 0:
                filtro = message.split('#')[1].strip()
                filter_string = " AND (linea LIKE '%-" + filtro + "-%' OR linea IS NULL)"
            else:
                filter_string = ""
        # save filter in global_variable
        slots_sets = update_global_variables(["filter_string"], [filter_string])

        message = "Ciao! Sono il tuo assistente digitale e sono qui per aiutarti!\n\nCome ti posso essere d'aiuto?"
        dispatcher.utter_message(message.replace("\n", "  \n"))
        return slots_sets


# data l'azione, chiede il tipo dell'entità tra quelli proposti
# se viene inserito il nome di un'entità, ne ricava il tipo
class ActionRetrieveTypes(Action):

    def name(self):
        return "action_retrieve_types"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 1)
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        root, filter_string = global_variables(["root", "filter_string"], tracker)
        
        action = tracker.get_slot("action_1").lower()
        cursor_tables.execute("SELECT DISTINCT entities FROM " + questions_table + filter_string.replace("AND", "WHERE") )
        entities = list(cursor_tables.fetchall())
        
        # se ha gia il nome dell'entità, mette a "true" lo slot "found_name" e termina l'azione
        if tracker.get_slot("name_1") is not None: 
            if len(tracker.get_slot("name_1")) > 0 and "esci" not in str(tracker.get_slot("name_1")).lower():
                conn.close()
                conn_tables.close()
                return [SlotSet("found_name", "true"), SlotSet("type_1", tracker.get_slot("type_1")), SlotSet("name_1", tracker.get_slot("name_1"))]
        elif tracker.get_slot("type_1") is not None:
            conn.close()
            conn_tables.close()
            return []
        
        # prende anche i sinonimi del verbo
        azioni = get_synonyms(cursor, action)
        azioni.add(action)
        
        # estrae tutti i tipi con azione = "action" (o sinonimi di "action") e li salva nel set "types_set"
        types_set = set()
        for ent in entities:
            e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
            if e["action"].lower() in azioni and str(e["entities"]).lower() != "none":
                for e1 in eval(e["entities"]):
                    types_set.add(e1["entity_type"].lower())
        
        
        message = ""
        # la root deve avere alcune caratteristiche per essere considerata tale
        global ignored_verbs
        if (root[-3:] in ["are", "ere", "ire"] or root[-4:] in ["arre", "orre", "urre"]) and root not in ignored_verbs:
            message = "Cosa vuoi " + root + "?\n"
        elif root == "avere informazioni":
            message = "In merito a cosa vuoi " + root + "?\n"
        else:
            message = "Che cosa in particolare?\n"

        type_set_with_synonyms = set()
        for t in types_set:
            if t.lower() != "none" and t not in type_set_with_synonyms:
                message = message + "- " + t + "\n"

            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + t + "'%\"")
            sinonimi = cursor.fetchall()
            if len(sinonimi) > 0:
                sinonimi = eval(sinonimi[0][0])
                for s in sinonimi:
                    type_set_with_synonyms.add(s)
            else:
                type_set_with_synonyms.add(t)
                    
        message = message + "(Oppure digita \"esci\" per uscire)"
        dispatcher.utter_message(message.replace("\n", "  \n"))
        
        conn.close()
        conn_tables.close()
        return []


# chiede il nome dell'entità
class ActionRetrieveName(Action):

    def name(self):
        return "action_retrieve_name"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 1)
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        action = tracker.get_slot("action_1").lower()
        entity_type = tracker.get_slot("type_1")
        
        # se ha gia il nome dell'entità, mette a "true" lo slot "found_name" e termina l'azione
        if tracker.get_slot("name_1") is not None:
            if len(tracker.get_slot("name_1")) > 0:
                conn.close()
                conn_tables.close()
                return [SlotSet("found_name", "true"), SlotSet("type_1", entity_type), SlotSet("name_1", tracker.get_slot("name_1"))]
        
        entity_name = []
        
        # estrazione di tutte le entità (e tipi) presenti nel database, salvandoli in set() (compresi i lemmi)
        # è utile nel codice seguente per verificare se l'utente ha inserito un tipo o un nome
        # le prende tutte e guarda in ActionRetrieveFaq se compare nella tripla
        root, filter_string = global_variables(["root", "filter_string"], tracker)

        types_set, entity_set = get_entities(cursor, conn_tables, cursor_tables, questions_table, filter_string)
        entity_set_lemma = get_entities_lemma(cursor, conn_tables, cursor_tables, questions_table, filter_string)
        entity_set = entity_set.union(entity_set_lemma)
        
        # se il type inserito non è un type si mette come entità e si gestisce in ActionRetrieveFaq
        if type(entity_type) == str:
            if "esci" in entity_type or set([entity_type]).intersection(set(types_set)) == set() or entity_type in entity_set: #entity_type not in types_set:
                entity_name = entity_type 
        else:
            if "esci" in entity_type or set(entity_type).intersection(set(types_set)) == set() or set(entity_type).issubset(set(entity_set)): #entity_type not in types_set:
                entity_name = entity_type
                
        if "esci" in entity_type or "esci" in entity_name:
            conn.close()
            conn_tables.close()
            return [SlotSet("found_name", "true"), SlotSet("type_1", "esci"), SlotSet("name_1", "esci")]
        if entity_name != []:
            conn.close()
            conn_tables.close()
            return[SlotSet("found_name", "true"), SlotSet("type_1", entity_type), SlotSet("name_1", entity_name)]
        
        message = ""
        global ignored_verbs
        if (root[-3:] in ["are", "ere", "ire"] or root[-4:] in ["arre", "orre", "urre"]) and root not in ignored_verbs:
            message = "Quale "
            if type(entity_type) == str: # stringa inserita nel form
                message = message + entity_type + " "
            else: #array di entity_type
                for e in entity_type:
                    message = message + e + "/"
            message = message[:-1] + " vuoi " + root + "?\n"
        elif root == "avere informazioni":
            message = "In merito a quale "
            if type(entity_type) == str: # stringa inserita nel form
                message = message + entity_type + " "
            else: #array di entity_type
                for e in entity_type:
                    message = message + e + "/"
            message = message[:-1] + " vuoi " + root + "?\n"
        else:
            message = "Quale "
            if type(entity_type) == str: # stringa inserita nel form
                message = message + entity_type + " "
            else:
                for e in entity_type:
                    message = message + e + "/"
            message = message[:-1] + " in particolare?\n"
        
        # prende anche i sinonimi del verbo
        azioni = get_synonyms(cursor, action)
        azioni.add(action)
                    
        # prende tutte le entita con type = entity_type e azione = action (o sinonimi), se non è vuota
        # prende anche le entita con type = entity_type e azione vuota
        cursor_tables.execute("SELECT DISTINCT entities FROM " + questions_table + filter_string.replace("AND", "WHERE") )
        entities = list(cursor_tables.fetchall())
        entity_set = set()
        for ent in entities:
            e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
            if action == "" and str(e["entities"]).lower() != "none":
                for e1 in eval(e["entities"]):
                    if e1["entity_type"].lower() in entity_type:
                        entity_set.add(e1["entity"].lower())
            elif str(e["entities"]).lower() != "none":
                for e1 in eval(e["entities"]):
                    if e1["entity_type"].lower() in entity_type and e["action"].lower() in azioni:
                        entity_set.add(e1["entity"].lower())
        
        # propone le entità trovate all'utente
        entity_set_with_synonyms = set()
        for e in entity_set:
            if e.lower() != "none" and e not in entity_set_with_synonyms:
                message = message + "- " + e + "\n"

            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e + "'%\"")
            sinonimi = cursor.fetchall()
            if len(sinonimi) > 0:
                sinonimi = eval(sinonimi[0][0])
                for s in sinonimi:
                    entity_set_with_synonyms.add(s)
            else:
                entity_set_with_synonyms.add(e)
                
        message = message + "(Oppure digita \"esci\" per uscire)"
        dispatcher.utter_message(message.replace("\n", "  \n"))
        
        conn.close()
        conn_tables.close()
        return [SlotSet("found_name", "false")]


# ritorna la risposta o, se non trova una tripla corrispondente sceglie quella più simile e chiede all'utente se intende quella
class ActionRetrieveFaq(Action):

    def name(self):
        return "action_retrieve_faq"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 1)
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        # estrazione global variables
        root, query_more_rows, more_rows, check_more_entities, action_only_action, entity_type_only_action, entity_only_action, only_action, filter_string = global_variables(["root", "query_more_rows", "more_rows", "check_more_entities", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action", "filter_string"], tracker)

        # Estrazione dell'azione dalla variabile globale o dallo slot
        entities = {}
        entities["action"] = ""
        if action_only_action != "" and action_only_action != []:
            if type(action_only_action) == str:
                entities["action"] = action_only_action.lower()
            else:
                entities["action"] = action_only_action
        else:
            entities["action"] = tracker.get_slot("action_1").lower()

        
        # Estrazione delle entità (e tipi) dalla variabile globale o dallo slot
        # se string = primo giro e cerca la risposta
        # se lista = secondo giro quindi basta la select per prendere la risposta
        tipi = []
        entita = []

        # secondo giro, dopo che l'utente ha scelto tra le faq proposte
        if more_rows > 0:
            tipi = tracker.get_slot("type_1")
            entita = tracker.get_slot("name_1")

        # primo giro, si estraggono entità e tipi che possono essere stringhe o liste
        else:
            if entity_type_only_action != "" and entity_type_only_action != []:
                if type(entity_type_only_action) != str:
                    for t in entity_type_only_action:
                        tipi.append(str(t).lower())
                else:
                    entities["entity_type"] = entity_type_only_action.lower()
            else:
                if type(tracker.get_slot("type_1")) != str:
                    for t in tracker.get_slot("type_1"):
                        tipi.append(str(t).lower())
                else:
                    entities["entity_type"] = tracker.get_slot("type_1").lower()
            if entity_only_action != "" and entity_only_action != []:
                if type(entity_only_action) != str:
                    for t in entity_only_action:
                        entita.append(str(t).lower())
                else:
                    entities["entity"] = entity_only_action.lower()
            else:
                if type(tracker.get_slot("name_1")) != str:
                    for t in tracker.get_slot("name_1"):
                        entita.append(str(t).lower())
                else:
                    entities["entity"] = tracker.get_slot("name_1").lower()

        # se in "type" e "name" c'è la stessa stringa e non è "esci", si cerca il tipo dell'entità name
        if tracker.get_slot("type_1") == tracker.get_slot("name_1") and type(tracker.get_slot("name_1")) == str and tracker.get_slot("name_1").lower() != "esci":
            cursor.execute("SELECT entity_type FROM entities WHERE entity LIKE '" + tracker.get_slot("name_1").lower() + "'")
            e_type = list(cursor.fetchall())
            if len(e_type) > 0:
                entities["entity_type"] = e_type[0][0]
            
        root = entities["action"]
        slots_sets = update_global_variables(["root"], [root])
        
        # se l'utente ha chiesto di USCIRE durante l'inserimento di nome o tipo
        message = ""
        if (tipi != [] and "esci" in tipi) or (entita != [] and "esci" in entita) or (tipi == [] and entities["entity_type"] == "esci") or (entita == [] and entities["entity"] == "esci") or entities["action"] == "esci":
            message = "Uscito.\nCome posso aiutarti?"
            dispatcher.utter_message(message.replace("\n", "  \n"))
            
            # salvataggio della conversazione
            save_conversation(tracker, "no", 1)
            
            # azzeramento delle variabili globali
            slots_sets = slots_sets + update_global_variables(["root", "more_rows", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", 0, [], [], [], 0])
            
            conn.close()
            conn_tables.close()
            return slots_sets + [SlotSet("action_1", None), SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("assertion", None), Restarted()]
        
        # generazione del dizionario in due modi diversi se le entità sono array o stringhe
        entities_query = {}
        if tipi == [] and entita == []: # primo giro
            entities_query = eval("{'action': '" + entities["action"] + "', 'entities': \"[{'entity_type': '" + entities["entity_type"] + "', 'entity': '" + entities["entity"] + "'}]\"}")
        else: # secondo giro
            ct = 0
            entities_array = []
            for e in entita:
                entities_array.append(eval("{'entity_type': '" + tipi[ct] + "', 'entity': '" + e + "'}"))
                ct = ct + 1
            entities_query["action"] = entities["action"]
            entities_query["entities"] = str(entities_array)

        if tipi == [] and entita == []:
            entita.append(entities["entity"])
        name = ""
        action_name = ""
        all_alternative = ""
        alternative = ""
        
        # preparazione della query con più entita' ed i sinonimi della varie entità
        if len(str(entities_query).split("{")) > 2:
            entities_query_prima_parte = str(entities_query).split("{'entity_type':")[0] # prende la prima parte
            entities_query_array = []
            for e in str(entities_query).split("\"[")[1].split(", {"):
                entities_query_array.append((entities_query_prima_parte + "{" + e.replace("]\"}", "") + "]").replace("{{", "{"))
            entities_query_with_and = " ("
            for e in entities_query_array:
                entities_query_with_and = entities_query_with_and + " entities REGEXP \"" + e.replace('"', "'").replace("{", ".*{").replace("}", "}.*").replace("[", "\\\[").replace("]", "\\\]") + "\" AND"
            entities_query_with_and = entities_query_with_and[:-4] + ")"
            
            # sinonimi dell'entità
            all_alternative = trova_sinonimi_entita(str(entities_query_with_and), entita)        
            for a in all_alternative:
                alternative = alternative + a + " OR "
            alternative = alternative[:-4]                               
        # preparazione della query con una sola entita' ed i sinonimi dell'entità
        else:
            all_alternative = trova_sinonimi_entita(str(entities_query), entita)
        
            for a in all_alternative:
                alternative = alternative + " entities REGEXP \"" + a.replace('"', "'").replace("{", ".*{").replace("}", "}.*").replace("[", "\\\[").replace("]", "\\\]") + "\" OR"
            alternative = alternative[:-3]
        
        # preparazione della query con anche l'azione ed i suoi sinonimi
        all_alternative = trova_sinonimi_entita(str(alternative), [entities["action"]])
        alternative = ""
        for a in all_alternative:
            alternative = alternative + " (" + a + ") OR"
        alternative = alternative[:-3]
        alternative_lemma = str(alternative).replace("entities REGEXP", "entities_lemma REGEXP")
        

        if more_rows > 0:
            cursor_tables.execute(query_more_rows)
        else:
            cursor_tables.execute("SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + str(alternative) + " OR " + str(alternative_lemma) + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10")
            query_more_rows = "SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + str(alternative) + " OR " + str(alternative_lemma) + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10"
        faq_title = cursor_tables.fetchall()

        ### ENTITA' LEMMA ###
        faq_title, query_more_rows = query_entities_lemma(faq_title, query_more_rows, entita)
        
        slots_sets = update_global_variables(["query_more_rows"], [query_more_rows])
        
        # se NON trova la tripla completa, prova senza il TIPO (e senza sinonimi del tipo)
        if len(faq_title) == 0:
            where_condition = str(alternative) + " OR " + str(alternative_lemma)
            where_condition = re.sub("'entity_type': '[a-z0-9 ]+'", "'entity_type': '.*'", where_condition)

            
            cursor_tables.execute("SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10")
            faq_title = cursor_tables.fetchall()
            
            query_more_rows = "SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10"
            slots_sets = slots_sets + update_global_variables(["query_more_rows"], [query_more_rows])

            ### ENTITA' LEMMA ###
            faq_title, query_more_rows = query_entities_lemma(faq_title, query_more_rows, entita)

            # se trova la faq senza il TIPO, la propone senza chiedere all'utente (si dà priorità ad azione ed entità corrette)
            if len(faq_title) != 0:
                # se ne trova una sola
                if len(faq_title) == 1:
                    faq_title = faq_title[0][0]
                # se ne trova più di una
                else:
                    more_rows = len(faq_title)
                    message = "Quale delle seguenti intendi?\n"
                    buttons = []
                    ct = 1
                    for f in faq_title:
                        faq_title = f[1]
                        action_name = faq_title.split("'")[3]
                        faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                        name = []
                        type_name = []
                        for e in eval(faq_title2):
                            name.append(e['entity'])
                            type_name.append(e['entity_type'])
                        buttons.append({"title": str(f[3]).lower(), "payload": str(ct)})
                        ct = ct + 1
                    conn.close()
                    conn_tables.close()
                    buttons.append({"title": "nessuna delle precedenti", "payload": str(ct)})
                    dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                    check_more_entities = 0
                    
                    slots_sets = slots_sets + update_global_variables(["more_rows", "check_more_entities"], [more_rows, check_more_entities])
                    return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]

            # se NON trova la faq senza il TIPO, prova togliendo anche l'AZIONE (e i sinonimi dell'azione)
            else:
                where_condition = re.sub("'action': '[a-z0-9 ]+'", "'action': '.*'", where_condition)
                    
                cursor_tables.execute("SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10")
                faq_title_1 = cursor_tables.fetchall()

                ### ENTITA' LEMMA ###
                query_more_rows = "SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10"
                faq_title_1, query_more_rows = query_entities_lemma(faq_title_1, query_more_rows, entita)
                
                # se trova la faq senza l'AZIONE e il TIPO
                if len(faq_title_1) != 0:
                    slots_sets = slots_sets + update_global_variables(["query_more_rows"], [query_more_rows])
                    
                    # se ne trova una sola, la propone all'utente chiedendo se è corretta
                    if len(faq_title_1) == 1:
                        faq_title = faq_title_1[0][1]
                        action_name = faq_title.split("'")[3]
                        faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                        name = []
                        type_name = []
                        for e in eval(faq_title2):
                            name.append(e['entity'])
                            type_name.append(e['entity_type'])
                        message = "Intendi: " + faq_title_1[0][3] + "?"
                        buttons = [{"title": "sì", "payload": "sì"}, {"title": "no", "payload": "no"}]
                        
                        dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                        conn.close()
                        conn_tables.close()
                        check_more_entities = 0
                        slots_sets = slots_sets + update_global_variables(["check_more_entities"], [check_more_entities])
                        return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]
                    # se ne trova più di una, le propone all'utente chiedendo se ce n'è una corretta
                    else:
                        more_rows = len(faq_title_1)
                        message = "Quale delle seguenti intendi?\n"
                        buttons = []
                        ct = 1
                        for f in faq_title_1:
                            faq_title = f[1]
                            action_name = faq_title.split("'")[3]
                            faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                            name = []
                            type_name = []
                            for e in eval(faq_title2):
                                name.append(e['entity'])
                                type_name.append(e['entity_type'])
                            buttons.append({"title": str(f[3]).lower(), "payload": str(ct)})
                            ct = ct + 1
                        conn.close()
                        conn_tables.close()
                        buttons.append({"title": "nessuna delle precedenti", "payload": str(ct)})
                        dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                        check_more_entities = 0
                        slots_sets = slots_sets + update_global_variables(["more_rows", "check_more_entities"], [more_rows, check_more_entities])
                        return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]
                
                # se NON trova la faq senza l'AZIONE e il TIPO, si cercano faq con ENTITA' IN COMUNE
                # se NON trova neanche quelle, si rimuovono solamente le ENTITA' (ed i relativi sinonimi)
                else:
                    # prima di togliere le entità si verifica se ci sono FAQ CON QUALCHE ENTITA' IN COMUNE
                    cursor_tables.execute("SELECT entities, id, frase FROM " + questions_table + " WHERE entities NOT LIKE \"%\'None\'%\" " + filter_string)
                    db_entities = list(cursor_tables.fetchall())
                    # dizionario contenente per ogni faq {id1: [ent1, ent2, ...], id2: [ent1, ent2, ...], ...}
                    all_entities = {}
                    min_len = len(entita)
                    # estrazione di tutte le entità di ogni faq e inserimento come valore nel dizionario, avente come chiave l'id della faq
                    for ent in db_entities:
                        ent1 = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))['entities']
                        row_entities = []
                        for e in eval(ent1):
                            row_entities.append(e['entity'])
                        all_entities[ent[1]] = row_entities
                        if len(row_entities) > min_len:
                            min_len = len(row_entities)

                    # si estraggono gli id ed entità che hanno almeno una entità in comune con la frase
                    # alla fine si tengono quelle che hanno più entità in comune con la domanda dell'utente
                    similar_entities = {}
                    for key, value in all_entities.items():
                        difference = []
                        if len(entita) > len(value) and len(set(entita).intersection(set(value))) > 0:
                            difference = list(set(entita) - set(value))
                        elif len(set(entita).intersection(set(value))) > 0:
                            difference = list(set(value) - set(entita))
                        if min_len > len(difference) and len(difference) > 0 and set(entita):
                            min_len = len(difference)
                            similar_entities = {}
                            similar_entities[key] = value
                        elif min_len == len(difference) and min_len != len(entita) and len(difference) > 0:
                                similar_entities[key] = value

                    # se trovo solo UNA FAQ con entità in comune
                    if len(similar_entities) == 1:
                        cursor_tables.execute("SELECT frase, entities FROM " + questions_table + " WHERE id = " + str(list(similar_entities.keys())[0]) + " " + filter_string + " LIMIT 10")
                        similar_row = list(cursor_tables.fetchall())
                        n_pla = similar_row[0][1]
                        action_name = n_pla.split("'")[3]
                        faq_title2 = eval(n_pla.replace("'[", "\"[").replace("]'", "]\""))['entities']
                        name = []
                        type_name = []
                        for e in eval(faq_title2):
                            name.append(e['entity'])
                            type_name.append(e['entity_type'])
                        message = "Intendi: " + similar_row[0][0] + "?"
                        buttons = [{"title": "sì", "payload": "sì"}, {"title": "no", "payload": "no"}]
                        
                        dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                        conn.close()
                        conn_tables.close()
                        check_more_entities = 0
                        slots_sets = slots_sets + update_global_variables(["check_more_entities"], [check_more_entities])
                        return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]

                    # se trovo PIU' DI UNA FAQ con lo stesso numero di entità in comune
                    elif len(similar_entities) > 1:
                        query_more_rows = "SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN " + str(list(similar_entities.keys())).replace("[", "(").replace("]", ")") + " " + filter_string
                        cursor_tables.execute(query_more_rows)
                        faq_title_1 = list(cursor_tables.fetchall())
                        slots_sets = slots_sets + update_global_variables(["query_more_rows"], [query_more_rows])
                        more_rows = len(similar_entities)

                        name = ""
                        type_name = ""
                        message = "Quale delle seguenti intendi?\n"
                        buttons = []
                        ct = 1
                        for f in faq_title_1:
                            faq_title = f[1]
                            action_name = faq_title.split("'")[3]
                            faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                            name = []
                            type_name = []
                            for e in eval(faq_title2):
                                name.append(e['entity'])
                                type_name.append(e['entity_type'])
                            buttons.append({"title": str(f[3]).lower(), "payload": str(ct)})
                            ct = ct + 1
                        conn.close()
                        conn_tables.close()
                        buttons.append({"title": "nessuna delle precedenti", "payload": str(ct)})
                        dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                        check_more_entities = 0
                        slots_sets = slots_sets + update_global_variables(["more_rows", "check_more_entities"], [more_rows, check_more_entities])
                        return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]


                    # se NON trova ENTITA' IN COMUNE, si rimuovono solamente le ENTITA' (ed i relativi sinonimi)
                    where_condition = str(alternative) + " OR " + str(alternative_lemma)
                    where_condition = re.sub("'entity': '[a-z0-9 ]+'", "'entity': '.*'", where_condition)
                        
                    cursor_tables.execute("SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10")
                    entities1 = cursor_tables.fetchall()
                    
                    # se trova la faq senza ENTITA
                    if len(entities1) != 0:
                        query_more_rows = "SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10"
                        slots_sets = slots_sets + update_global_variables(["query_more_rows"], [query_more_rows])
                        
                        # se ne trova una sola, la propone all'utente chiedendo se è corretta
                        if len(entities1) == 1:
                            entities1 = entities1[0][1]
                            action_name = entities1.split("'")[3]
                            entities2 = eval(entities1.replace("'[", "\"[").replace("]'", "]\""))['entities']
                            name = []
                            type_name = []
                            for e in eval(entities2):
                                name.append(e['entity'])
                                type_name.append(e['entity_type'])
                            message = "Intendi: " + entities1[0][3] + "?"
                            buttons = [{"title": "sì", "payload": "sì"}, {"title": "no", "payload": "no"}]

                            dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                            conn.close()
                            conn_tables.close()
                            check_more_entities = 0
                            slots_sets = slots_sets + update_global_variables(["check_more_entities"], [check_more_entities])
                            return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]

                        # se ne trova più di una, le propone all'utente chiedendo se ce n'è una corretta
                        else:
                            more_rows = len(entities1)
                            message = "Quale delle seguenti intendi?\n"
                            buttons = []
                            ct = 1
                            for f in entities1:
                                faq_title = f[1]
                                action_name = faq_title.split("'")[3]
                                faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                                name = []
                                type_name = []
                                for e in eval(faq_title2):
                                    name.append(e['entity'])
                                    type_name.append(e['entity_type'])
                                buttons.append({"title": str(f[3]).lower(), "payload": str(ct)})
                                ct = ct + 1
                            conn.close()
                            conn_tables.close()
                            buttons.append({"title": "nessuna delle precedenti", "payload": str(ct)})
                            dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                            check_more_entities = 0
                            slots_sets = slots_sets + update_global_variables(["more_rows", "check_more_entities"], [more_rows, check_more_entities])
                            return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]
                    
                    # se NON trova la faq senza ENTITA, si rimuovono AZIONE ed ENTITA'
                    else:
                        where_condition = re.sub("'action': '[a-z0-9 ]+'", "'action': '.*'", where_condition)
                        
                        cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + str(entities["action"]) + "'%\"")
                        sinonimo_action = cursor.fetchall()
                        if len(sinonimo_action) > 0:
                            sinonimo_action = eval(sinonimo_action[0][0])
                            for s in sinonimo_action:
                                where_condition = where_condition.replace("'action': '" + str(s), "'action': '.*")
                        else:
                            where_condition = where_condition.replace("'action': '" + str(entities["action"]), "'action': '.*")
                            
                        cursor_tables.execute("SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10")
                        faq_title_1 = cursor_tables.fetchall()
                        
                        # se trova la faq senza l'AZIONE e l'ENTITA
                        if len(faq_title_1) != 0:
                            query_more_rows = "SELECT faq_title, entities, id, frase FROM " + questions_table + " WHERE id IN ( SELECT MIN(id) FROM " + questions_table + " WHERE" + where_condition + filter_string + " GROUP BY faq_title)" + filter_string + " ORDER BY id LIMIT 10"
                            slots_sets = slots_sets + update_global_variables(["query_more_rows"], [query_more_rows])

                            # se ne trova una sola, la propone all'utente chiedendo se è corretta
                            if len(faq_title_1) == 1:
                                faq_title = faq_title_1[0][1]
                                action_name = faq_title.split("'")[3]
                                faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                                name = []
                                type_name = []
                                for e in eval(faq_title2):
                                    name.append(e['entity'])
                                    type_name.append(e['entity_type'])
                                message = "Intendi: " + faq_title_1[0][3] + "?"
                                buttons = [{"title": "sì", "payload": "sì"}, {"title": "no", "payload": "no"}]
                                
                                dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                                conn.close()
                                conn_tables.close()
                                check_more_entities = 0
                                slots_sets = slots_sets + update_global_variables(["check_more_entities"], [check_more_entities])
                                return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]

                            # se ne trova più di una, le propone all'utente chiedendo se ce n'è una corretta
                            else:
                                more_rows = len(faq_title_1)
                                message = "Quale delle seguenti intendi?\n"
                                buttons = []
                                ct = 1
                                for f in faq_title_1:
                                    faq_title = f[1]
                                    action_name = faq_title.split("'")[3]
                                    faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                                    name = []
                                    type_name = []
                                    for e in eval(faq_title2):
                                        name.append(e['entity'])
                                        type_name.append(e['entity_type'])
                                    buttons.append({"title": str(f[3]).lower(), "payload": str(ct)})
                                    ct = ct + 1
                                conn.close()
                                conn_tables.close()
                                buttons.append({"title": "nessuna delle precedenti", "payload": str(ct)})
                                dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                                check_more_entities = 0
                                slots_sets = slots_sets + update_global_variables(["more_rows", "check_more_entities"], [more_rows, check_more_entities])
                                return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]
                        
                        # se NON trova la faq senza l'AZIONE e l'ENTITA
                        else:
                            # Il chatbot non è in grado di trovare una risposta
                            message = "Mi dispiace, non conosco la risposta a questa tua domanda.\n\nCome posso aiutarti?"
                            dispatcher.utter_message(message.replace("\n", "  \n"))
                            
                            # salvataggio della conversazione
                            save_conversation(tracker, "no", 1)
                            
                            # azzeramento delle variabili globali
                            slots_sets = slots_sets + update_global_variables(["root", "check_more_entities", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", 0, [], [], [], 0])
                            
                            conn.close()
                            conn_tables.close()
                            return slots_sets + [SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("action_1", None), SlotSet("assertion", None), Restarted()]
                            
        # se trova la tripla completa ma con una entita sola (la frase iniziale ne aveva due)
        elif check_more_entities > 0:
            faq_title = faq_title[0][0]
            cursor_tables.execute("SELECT frase FROM " + questions_table + " WHERE faq_title = \"" + faq_title + "\"" + filter_string)
            frase = cursor_tables.fetchall()[0][0]
            
            message = "Intendi: " + frase + "?"
            buttons = [{"title": "sì", "payload": "sì"}, {"title": "no", "payload": "no"}]
            dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
            conn.close()
            conn_tables.close()
            check_more_entities = 0
            slots_sets = slots_sets + update_global_variables(["check_more_entities"], [check_more_entities])
            return slots_sets + [SlotSet("assertion", None)]
        
        # se trova la tripla completa
        else:
            if more_rows == 0 and len(faq_title) == 1:
                faq_title = faq_title[0][0]
            elif more_rows == 0 and len(faq_title) > 1:
                more_rows = len(faq_title)
                message = "Quale delle seguenti intendi?\n"
                buttons = []
                ct = 1
                for f in faq_title:
                    faq_title = f[1]
                    action_name = faq_title.split("'")[3]
                    faq_title2 = eval(faq_title.replace("'[", "\"[").replace("]'", "]\""))['entities']
                    name = []
                    type_name = []
                    for e in eval(faq_title2):
                        name.append(e['entity'])
                        type_name.append(e['entity_type'])
                    buttons.append({"title": str(f[3]).lower(), "payload": str(ct)})
                    ct = ct + 1
                conn.close()
                conn_tables.close()
                buttons.append({"title": "nessuna delle precedenti", "payload": str(ct)})
                dispatcher.utter_message(message.replace("\n", "  \n"), buttons=buttons)
                check_more_entities = 0
                slots_sets = slots_sets + update_global_variables(["more_rows", "check_more_entities"], [more_rows, check_more_entities])
                return slots_sets + [SlotSet("action_1", action_name), SlotSet("type_1", type_name), SlotSet("name_1", name), SlotSet("check_another_faq", "si"), SlotSet("assertion", None)]
            else:
                faq_title = faq_title[more_rows - 1][0]
                more_rows = 0
            
        faq_title_finale = global_variables(["faq_title_finale"], tracker)
        faq_title_finale = faq_title
        
        cursor_tables.execute("SELECT frase FROM " + answers_table + " WHERE faq_title = \"" + faq_title + "\"")
        message = eval("'''" + cursor_tables.fetchall()[0][0].replace("\\", "\\\\").replace("\\U", "U") + "'''")
        dispatcher.utter_message(message.replace("\n", "  \n"))
        
        conn.close()
        conn_tables.close()
        check_more_entities = 0
        slots_sets = slots_sets + update_global_variables(["more_rows", "faq_title_finale", "check_more_entities"], [more_rows, faq_title_finale, check_more_entities])
        return slots_sets + [SlotSet("action_1", None), SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("assertion", None)]
        
    

# inserisce il verbo nello slot
class ActionSetAction(Action):

    def name(self):
        return "action_set_action"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 0)
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        
        root, filter_string = global_variables(["root", "filter_string"], tracker)
        
        # estrazione di azione ed entità dalla frase inserita dall'utente, creando un json
        entities, no_action = json_generator(tracker.latest_message['text'].lower(), tracker)
        root = entities['action']
        slots_sets = update_global_variables(["root"], [root])
        entity_type = []
        entity = []
        if eval(entities['entities']) != []:
            for e in eval(entities['entities']):
                entity_type.append(e['entity_type'])
                entity.append(e['entity'])
        # se non è stata inserita nessuna entità e nessun verbo, si chiede di ripetere l'inserimento
        else:
            if no_action == True:
                return [FollowupAction("action_custom_fallback")]

        # estrazione di tutti gli entity type, e si cerca se sono presenti nella frase
        cursor_tables.execute("SELECT DISTINCT entities FROM " + questions_table + filter_string.replace("AND", " WHERE"))
        entities = list(cursor_tables.fetchall())
        types_set = set()
        for ent in entities:
            e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
            if str(e["entities"]).lower() != "none":
                for e1 in eval(e["entities"]):
                    types_set.add(e1["entity_type"].lower())
        # si cerca se sono presenti nella frase
        for ent_type in types_set:
            if findWholeWord(ent_type)(tracker.latest_message['text'].lower()) != None:
                entity_type.append(ent_type)
                
        slots_sets = slots_sets + update_global_variables(["root"], [root])
            
        conn.close()
        conn_tables.close()

        if len(entity) == 0 and len(entity_type) == 0:
            return slots_sets + [SlotSet("action_1", root)]
        elif len(entity) == 0:
            return slots_sets + [SlotSet("action_1", root), SlotSet("type_1", entity_type)]
        else:
            return slots_sets + [SlotSet("action_1", root), SlotSet("type_1", entity_type), SlotSet("name_1", entity), SlotSet("found_name", "true")]



# azione per uscire e resettare slot e variabili
class ActionExit(Action):

    def name(self):
        return "action_exit"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        
        # estrazione global variables
        root, action_only_action, entity_type_only_action, entity_only_action, only_action, email_slot = global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action", "email_slot"], tracker)
        
        message = "Come posso aiutarti?"
        dispatcher.utter_message(message.replace("\n", "  \n"))
        
        assertion = tracker.get_slot("assertion")
        
        # se il bot non ha saputo rispondere correttamente all'utente, salva conversazione con "result"="no"
        if assertion == "no":
            # salvataggio della conversazione
            save_conversation(tracker, "no", 1)
            
        # se il bot ha saputo rispondere correttamente all'utente, salva conversazione con "result"="si"
        else:
            # salvataggio della conversazione
            save_conversation(tracker, "sì", 1)
        
        # azzeramento delle variabili globali
        slots_sets = update_global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", [], [], [], 0])

        conn.close()
        conn_tables.close()
        return slots_sets + [SlotSet("action_1", None), SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("assertion", None), SlotSet("found_name", "false"), Restarted(), SlotSet("email_slot", email_slot)]



class TypeForm(FormAction):

    def name(self):
        return "type_form"
    
    @staticmethod
    def required_slots(tracker):
        return ["type_1"]
    
    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        return { "type_1": [ self.from_text(intent=None) ] }
    
    def submit(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> List[Dict]:
        return []
    
    def validate_type_1(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> Dict[Text, Any]:
        db_connection_last_interaction()
        
        value = re.sub("[^a-zA-Z0-9 àèéìòù]+", " ", str(value.strip().lower()))
        value = re.sub(" +", " ", value)
        value = encode_emoji(value)

        filter_string = global_variables(["filter_string"], tracker)
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        types_set, entities_set = get_entities(cursor, conn_tables, cursor_tables, questions_table, filter_string)

        max_len = 0
        type_or_entity = ""
        type_or_entity_levenstein = ""
        for t in types_set:
            if findWholeWord(t)(value) != None and len(t) > max_len:
                type_or_entity = t
                max_len = len(t)
            else:
                min_lev_distance = len(t)
                max_lev_distance = int(len(t)/100 * 20) # 20%
                lev = calculate_levenshtein_distance(t, value)
                if lev <= max_lev_distance and lev < min_lev_distance:
                    min_lev_distance = lev
                    type_or_entity_levenstein = t

        max_len = 0
        for e in entities_set:
            if findWholeWord(e)(value) != None and len(e) > max_len:
                type_or_entity = e
                max_len = len(e)
            else:
                min_lev_distance = len(e)
                max_lev_distance = int(len(e)/100 * 20) # 20%
                lev = calculate_levenshtein_distance(e, value)
                if lev <= max_lev_distance and lev < min_lev_distance:
                    min_lev_distance = lev
                    type_or_entity_levenstein = e

        if len(type_or_entity) == 0 and len(type_or_entity_levenstein) != 0:
            type_or_entity = type_or_entity_levenstein

        if len(type_or_entity) != 0:
            return {"type_1": type_or_entity}
        elif len(type_or_entity) == 0 and len(value) > 0:
            return {"type_1": value}
        else:
            dispatcher.utter_message("La risposta non può essere vuota.  \nRipeti l'inserimento.")
            return {"type_1": None}



class NameForm(FormAction):

    def name(self):
        return "name_form"
    
    @staticmethod
    def required_slots(tracker):
        return ["name_1"]
    
    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        return { "name_1": [ self.from_text(intent=None) ] }
    
    def submit(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> List[Dict]:
        return []
    
    def validate_name_1(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> Dict[Text, Any]:
        db_connection_last_interaction()
        
        value = re.sub("[^a-zA-Z0-9 àèéìòù]+", " ", str(value.strip().lower()))
        value = re.sub(" +", " ", value)
        value = encode_emoji(value)
        
        filter_string = global_variables(["filter_string"], tracker)
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        types_set, entities_set = get_entities(cursor, conn_tables, cursor_tables, questions_table, filter_string)

        max_len = 0
        entity = []
        entity_levenstein = ""
        for e in entities_set:
            if findWholeWord(e)(value) != None and len(e) > max_len:
                entity = e
                max_len = len(e)
            else:
                min_lev_distance = len(e)
                max_lev_distance = int(len(e)/100 * 20) # 20%
                lev = calculate_levenshtein_distance(e, value)
                if lev <= max_lev_distance and lev < min_lev_distance:
                    min_lev_distance = lev
                    entity_levenstein = e

        if len(entity) == 0 and len(entity_levenstein) != 0:
            entity = entity_levenstein

        if len(entity) != 0:
            return {"name_1": entity}
        elif len(entity) == 0 and len(value) > 0:
            return {"name_1": value}
        else:
            dispatcher.utter_message("La risposta non può essere vuota.  \nRipeti l'inserimento.")
            return {"name_1": None}



class AssertionForm(FormAction):

    def name(self):
        return "assertion_form"
    
    @staticmethod
    def required_slots(tracker):
        return ["assertion"]
    
    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        return { "assertion": [ self.from_text(intent=None) ] }
    
    def submit(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> List[Dict]:
        return []
    
    def validate_assertion(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> Dict[Text, Any]:
        db_connection_last_interaction()
        
        more_rows = global_variables(["more_rows"], tracker)
        
        # Se "more_rows" == 0, si estra una risposta affermativa oppure negative
        if more_rows == 0:
            value = str(value).lower().replace('ì', 'i').replace('ò', 'o').strip()
            value = re.sub('i+', 'i', value)
            value = re.sub('o+', 'o', value)
            value = re.sub(',', '', value)
            value = re.sub('\.', '', value)
        
            # SI
            if value in ["si", "certo", "si grazie", "ovvio", "certamente", "ovviamente", "si certo", "giusto", "si giusto", "corretto", "esatto", "ok", "yes", "va bene", "okay"]:
                return {"assertion": "si"}

            # NO
            if value in ["no", "sbagliato", "errato", "hai sbagliato", "scorretto", "falso"]:
                return {"assertion": "no"}

            # Non valido
            dispatcher.utter_message("Risposta non valida.  \nRispondere con \"sì\" oppure \"no\".")
            return {"assertion": None}
        
        # Se "more_rows" != 0, si estra l'indice della risposta corretta tra quelle precedentemente proposte all'utente
        else:
            try:
                value = int(value.strip())
            except:
                dispatcher.utter_message("Risposta non valida.  \nRispondere con il numero corrispondente alla domanda scelta.")
                return {"assertion": None}
            
            if value >= 1 and value <= more_rows + 1:
                if value == more_rows + 1:
                    more_rows = 0
                    return {"assertion": "no", "more_rows": more_rows}
                else:
                    more_rows = value
                    return {"assertion": "si", "more_rows": more_rows}
            else:
                dispatcher.utter_message("Risposta non valida.  \nRispondere con il numero corrispondente alla domanda scelta.")
                return {"assertion": None}
            
# azione di fallback che risponde con una faq avente tripla simile se presente, altrimenti ritorna un messaggio di errore
# scrive nella tabella fallback_events gli ultimi 100 eventi ogni volta che entra in questa funzione
class ActionCustomFallback(Action):

    def name(self):
        return "action_custom_fallback"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        global global_nlp
        nlp_fallback = global_nlp
        global min_similarity_fallback
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        filter_string = global_variables(["filter_string"], tracker)
        
        # se la domanda/frase inserita dall'utente è vuota (togliendo gli spazi) ritorna un messaggio di errore
        # non si riporta nulla nella tabella "fallback_events" poiché l'utente non aveva scritto nulla
        question = tracker.latest_message['text'].lower()
        if question.replace(" ", "") == "":
            message = "Scusa, non ho capito, sii più preciso specificando azione e nome.\nCome posso aiutarti?"
            dispatcher.utter_message(message.replace("\n", "  \n"))
            return [UserUtteranceReverted()]
        
        # prende tutte le {entita:tipo} più i relativi sinonimi dell'entità (anche lemmi)
        types_set, entity_set, spacy_entities = get_entities(cursor, conn_tables, cursor_tables, questions_table, filter_string, True)
        entity_set_lemma, spacy_entities_lemma = get_entities_lemma(cursor, conn_tables, cursor_tables, questions_table, filter_string, True)
        entita1 = list(entity_set.union(entity_set_lemma))
        spacy_entities.update(spacy_entities_lemma)
                    
        # estrazione di azione ed entità dalla frase inserita dall'utente, creando un json
        entities, no_action = json_generator(question, tracker)
        root = entities['action']
        slots_sets = update_global_variables(["root"], [root])
        entity_question = []
        found_entity = False
        if eval(entities['entities']) != []:
            found_entity = True
        
        # se sono presenti entità nella frase
        if found_entity:
            cursor_tables.execute("SELECT entities, faq_title FROM " + questions_table + " WHERE entities NOT LIKE \"%\'entities\': \'None\'%\"" + filter_string)
            entities = list(cursor_tables.fetchall())
            max_similarity = 0
            message = "Scusa, non ho capito, sii più preciso specificando azione e nome.\nCome posso aiutarti?"
            
            # estrae tutti i sinonimi dell'entità e ne fa NLP
            doc2 = nlp_fallback(root)
            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + root + "'%\"")
            root_synonyms_query = cursor.fetchall()
            if len(root_synonyms_query) > 0:
                root_synonyms_query = eval(list(root_synonyms_query)[0][0])
            root_synonyms_nlp = []
            root_synonyms_list = []
            for s in root_synonyms_query:
                root_synonyms_nlp.append(nlp_fallback(s))
                root_synonyms_list.append(s)
            root_synonyms_nlp.append(doc2)
            
            for ent in entities:
                e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
                all_entita_faq_title_1 = []
                
                # estrae tutte le entità della frase
                for e1 in eval(e['entities']):
                    all_entita_faq_title_1.append(e1["entity"])
                    
                # se c'è un'altra faq con la stessa entità, si guarda la similarità tra le action
                # si tiene la faq_title con stessa entità e la similarità più alta tra le azioni
                # che deve superarre anche la soglia "min_similarity_fallback"
                if set(entita1).intersection(set(all_entita_faq_title_1)) != set():
                    if e['action'] in root_synonyms_list:
                        message = ent[1]
                        break
                    doc1 = nlp_fallback(e['action'])
                    for s in root_synonyms_nlp:
                        similarity = doc1.similarity(s)
                        if similarity > min_similarity_fallback and similarity > max_similarity:
                            max_similarity = similarity
                            message = ent[1]
            # message contiene la "faq_title" della risposta da restituire, sempre se ne ha trovato una
            cursor_tables.execute("SELECT frase FROM " + answers_table + " WHERE faq_title = \"" + message + "\"")
            risposta = cursor_tables.fetchall()
            if len(risposta) > 0:
                risposta = eval("'''" + risposta[0][0].replace("\\", "\\\\").replace("\\U", "U") + "'''")
                message = risposta + "\n\nCome posso aiutarti?"
            dispatcher.utter_message(message.replace("\n", "  \n"))
            
            # anche in questo caso si riporta nella tabella "fallback_events" che il bot è finito nell'azione di fallback
            save_fallback_conversation(tracker, message)
            conn.close()
            conn_tables.close()

            return slots_sets + [UserUtteranceReverted()]
                        
        # se NON sono presenti entità nella frase
        else:            
            # toglie dalla frase dell'utente le parole con poca importanza per migliorare la similarità
            # tiene solamente: nomi (comuni e propri) e verbi (anche ausiliari)
            small_question = ""
            doc = nlp_fallback(question)
            for t in doc:
                if t.pos_ == "NOUN" or t.pos_ == "VERB" or t.pos_ == "AUX" or t.pos_ == "PROPN":
                    small_question = small_question + " " + t.text
                    
            message = "Scusa, non ho capito, sii più preciso specificando azione e nome.\nCome posso aiutarti?"
            max_similarity = 0
            doc1 = nlp_fallback(small_question) # NLP della frase accorciata dell'utente
            
            # estrazione dei sinonimi dell'azione
            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + root + "'%\"")
            root_synonyms_query = cursor.fetchall()
            if len(root_synonyms_query) > 0:
                root_synonyms_query = eval(list(root_synonyms_query)[0][0])
            root_synonyms_nlp = []
            # per ogni sinonimo, si sostituisce con l'azione nella frase e si salva NLP
            for s in root_synonyms_query:
                root_synonyms_nlp.append(nlp_fallback(small_question.replace(root, s[0])))
            root_synonyms_nlp.append(doc1)
            
            # estrazione di tutte le frasi prive di entità (come quella dell'utente)
            cursor_tables.execute("SELECT frase, faq_title FROM " + questions_table + " WHERE entities LIKE \"%\'entities\': \'None\'%\"" + filter_string)
            sentences = list(cursor_tables.fetchall())
            for sentence in sentences:
                s = sentence[0]
                doc_temp = nlp_fallback(s)
                small_sentence = ""
                # per ciascuna frase anche qui si tengono solamente: nomi (comuni e propri) e verbi (anche ausiliari)
                for t in doc_temp:
                    if t.pos_ == "NOUN" or t.pos_ == "VERB" or t.pos_ == "AUX" or t.pos_ == "PROPN":
                        small_sentence = small_sentence + " " + t.text
                doc2 = nlp_fallback(small_sentence) # NLP della frase estratta dal DB, accorciata
                # si calcola la similarità tra tutte le frasi estratte dal DB e la frase dell'utente
                # comprese le varianti ottenute dai sinonimi dell'azione
                for s in root_synonyms_nlp:
                    similarity = doc2.similarity(s)
                    # si tiene la "faq_title" della frase più simile che supera anche la soglia "min_similarity_fallback"
                    if similarity > min_similarity_fallback and similarity > max_similarity:
                        max_similarity = similarity
                        message = sentence[1]
                    
            # message contiene la "faq_title" della risposta da restituire, sempre se ne ha trovato una
            cursor_tables.execute("SELECT frase FROM " + answers_table + " WHERE faq_title = \"" + message + "\"")
            risposta = cursor_tables.fetchall()
            if len(risposta) > 0:
                risposta = eval("'''" + risposta[0][0].replace("\\", "\\\\").replace("\\U", "U") + "'''")
                message = risposta + "\n\nCome posso aiutarti?"
            dispatcher.utter_message(message.replace("\n", "  \n"))
            
            # anche in questo caso si riporta nella tabella "fallback_events" che il bot è finito nell'azione di fallback
            save_fallback_conversation(tracker, message)
            conn.close()
            conn_tables.close()

            return slots_sets + [UserUtteranceReverted()]



# funzione che  svuota (mette a None) lo slot "assertion" quando necessario
class ActionResetAssertion(Action):

    def name(self):
        return "action_reset_assertion"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 1)
        return [SlotSet("action_1", None), SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("assertion", None)]



###########################################################################
######################## ONLY ACTION & ONLY ENTITY ########################
###########################################################################

# propone una lista di entità che corrispondono con il tipo inserito dall'utente
class ActionRetrieveNameOnlyAction(Action):

    def name(self):
        return "action_retrieve_name_only_action"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 1)

        action_only_action, entity_type_only_action, entity_only_action, filter_string = global_variables(["action_only_action", "entity_type_only_action", "entity_only_action", "filter_string"], tracker)
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()

        action = action_only_action
        if action_only_action is not None and type(action_only_action) == str:
            action = action.lower()
        entity_type = entity_type_only_action
        
        # se è già stato scritto il nome dell'entità si mette "found-name" a true
        if len(entity_only_action) > 0 and "esci" not in str(entity_only_action).lower():
            conn.close()
            conn_tables.close()
            entity_type_only_action = entity_type
            slots_sets = update_global_variables(["entity_type_only_action"], [entity_type_only_action])
            return slots_sets + [SlotSet("found_name", "true")]
        
        entity_name = []
        types_set, entity_set = get_entities(cursor, conn_tables, cursor_tables, questions_table, filter_string)
        entity_set_lemma = get_entities_lemma(cursor, conn_tables, cursor_tables, questions_table, filter_string)
        entity_set = entity_set.union(entity_set_lemma)
                    
        # se è una parola out-topic ("esci" o altro) la si mette come entità e si gestisce in ActionRetrieveFaq
        if "esci" in entity_type or set([entity_type]).intersection(set(types_set)) == set() or set([entity_type]).intersection(set(entity_set)) != set():
            entity_name = entity_type 
            entity_only_action = entity_type
        if "esci" in entity_type or "esci" in entity_name:
            conn.close()
            conn_tables.close()
            entity_type_only_action = "esci"
            entity_only_action = "esci"
            slots_sets = update_global_variables(["entity_type_only_action", "entity_only_action"], [entity_type_only_action, entity_only_action])
            return slots_sets + [SlotSet("found_name", "true")]
        if entity_name != []:
            conn.close()
            conn_tables.close()
            entity_type_only_action = entity_type
            entity_only_action = entity_name
            slots_sets = update_global_variables(["entity_type_only_action", "entity_only_action"], [entity_type_only_action, entity_only_action])
            return slots_sets + [SlotSet("found_name", "true"), SlotSet("name_1", entity_name)]
        
        slots_sets = update_global_variables(["entity_only_action"], [entity_only_action])
    
        entity_type_only_action = entity_type
        slots_sets = slots_sets + update_global_variables(["entity_type_only_action"], [entity_type_only_action])
        
        # date azione e tipo, si suggeriscono all'utente le possibili entità
        message = ""
        global ignored_verbs
        if (action != "" and action != []) and (action_only_action[-3:] in ["are", "ere", "ire"] or action_only_action[-4:] in ["arre", "orre", "urre"]) and action_only_action not in ignored_verbs:
            message = "Quale " + entity_type + " vuoi " + action_only_action + "?\n"
        else:
            message = "Quale " + entity_type + " in particolare?\n"
        
        # si utilizzano anche i sinonimi del verbo per estrarre più entità accettabili
        azioni = set()
        if action != "" and action != []:
            azioni = get_synonyms(cursor, action)
            azioni.add(action)
                    
        cursor_tables.execute("SELECT DISTINCT entities FROM " + questions_table + filter_string.replace("AND", "WHERE"))
        entities = list(cursor_tables.fetchall())
        entity_for_this_type = set()
        for ent in entities:
            e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
            if (action == "" or action == []) and str(e["entities"]).lower() != "none":
                for e1 in eval(e["entities"]):
                    if e1["entity_type"].lower() == entity_type and e1["entity"].lower() != "none":
                        entity_for_this_type.add(e1["entity"])
            elif str(e["entities"]).lower() != "none":
                for e1 in eval(e["entities"]):
                    if e1["entity_type"].lower() == entity_type and e["action"] in azioni and e1["entity"].lower() != "none":
                        entity_for_this_type.add(e1["entity"])
        
        entity_set_with_synonyms = set()
        for e in entity_for_this_type:
            if e.lower() != "none" and e not in entity_set_with_synonyms:
                message = message + "- " + e + "\n"

            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e + "'%\"")
            sinonimi = cursor.fetchall()
            if len(sinonimi) > 0:
                sinonimi = eval(sinonimi[0][0])
                for s in sinonimi:
                    entity_set_with_synonyms.add(s)
            else:
                entity_set_with_synonyms.add(e)
                
        message = message + "(Oppure digita \"esci\" per uscire)"
        dispatcher.utter_message(message.replace("\n", "  \n"))
        
        conn.close()
        conn_tables.close()
        return slots_sets + [SlotSet("found_name", "false")]



# salva il tipo o l'entità quando viene inserito solo il tipo o l'entità
class ActionSetActionTypeOnlyAction(Action):

    def name(self):
        return "action_set_action_type_only_action"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 0)
        global global_nlp
        nlp = global_nlp
        
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()

        # estrazione global variables
        root, action_only_action, entity_type_only_action, entity_only_action, only_action, filter_string = global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action", "filter_string"], tracker)
        
        only_action = 0 # indica che è stata inserita solamente l'entità o il tipo
        slots_sets = update_global_variables(["only_action"], [only_action])
        type_name_set = set()

        # estrae tutti i tipi, le entità ed i sinonimi delle entità. Salva tutto nel set "type_name_set"
        for column in ["entities", "entities_lemma"]:
            cursor_tables.execute("SELECT " + column + " FROM " + questions_table + filter_string.replace("AND", "WHERE"))
            entities = list(cursor_tables.fetchall())
            # estrae tutte le entità ed i tipi dal db ed i relativi sinonimi
            for ent in entities:
                e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
                if str(e['entities']).lower() != "none":
                    for e1 in eval(e['entities']):
                        type_name_set.add(e1["entity"].lower())
                        type_name_set.add(e1["entity_type"].lower())
                        cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e1['entity'] + "'%\"")
                        words = cursor.fetchall()
                        if len(words) != 0:
                            sinonimi = eval(words[0][0])
                            for s in sinonimi:
                                type_name_set.add(s.lower())

        # frase composta dai lemmi
        frase_lemma = ""
        doc_domanda = nlp(tracker.latest_message['text'].lower().strip())
        for d in doc_domanda:
            frase_lemma = frase_lemma + d.lemma_ + " "

        # se ci sono parole extra oltre all'entità le esclude
        max_len = 0
        type_or_entity = ""
        for type_entity in type_name_set:
            if (findWholeWord(type_entity)(tracker.latest_message['text'].lower()) != None or findWholeWord(type_entity)(frase_lemma) != None) and len(type_entity) > max_len:
                type_or_entity = type_entity
                max_len = len(type_entity)

        # se la parola non è presente nel set di entità e tipi
        if type_or_entity == "":
            message = "Scusa, non ho capito, sii più preciso specificando azione e nome."
            dispatcher.utter_message(message.replace("\n", "  \n"))
            
            # salvataggio della conversazione
            save_conversation(tracker, "no", 1)

            # azzeramento delle variabili globali
            slots_sets = slots_sets + update_global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", [], [], [], 0])

            conn.close()
            conn_tables.close()
            return slots_sets + [Restarted()]

        # se è nel set di entità e tipi
        type_or_entity_lemma = ""
        for token in nlp(type_or_entity):
            type_or_entity_lemma = type_or_entity_lemma + " " + token.lemma_
        type_or_entity_lemma = type_or_entity_lemma.strip()
        if len(entities) != 0:
            for ent in entities:
                e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
                if str(e['entities']).lower() != "none":
                    for e1 in eval(e['entities']):
                        cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e1['entity'] + "'%\"")
                        words = cursor.fetchall()
                        sinonimi = set()
                        sinonimi.add(e1['entity'].lower())
                        if len(words) != 0:
                            for w in eval(words[0][0]):
                                sinonimi.add(w.lower())
                        # se la parola inserita dall'utente è una entità, salva nome e tipo
                        if type_or_entity in sinonimi or type_or_entity_lemma in sinonimi:
                            entity_type_only_action = e1['entity_type']
                            entity_only_action = e1['entity']
                            conn.close()
                            conn_tables.close()
                            slots_sets = update_global_variables(["entity_type_only_action", "entity_only_action"], [entity_type_only_action, entity_only_action])
                            return slots_sets

            # se la parola inserita dall'utente NON è una entità, salva solamente il tipo
            entity_type_only_action = type_or_entity
            conn.close()
            conn_tables.close()
            slots_sets = slots_sets + update_global_variables(["entity_type_only_action"], [entity_type_only_action])
            return slots_sets
    
    
    
class ActionForm(FormAction):

    def name(self):
        return "action_form"
    
    @staticmethod
    def required_slots(tracker):
        return ["action_1"]
    
    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        return { "action_1": [ self.from_text(intent=None) ] }
    
    def submit(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> List[Dict]:
        return []
    
    def validate_action_1(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> Dict[Text, Any]:
        db_connection_last_interaction()
        save_conversation(tracker, "", 1)
        
        value = re.sub("[^a-zA-Z0-9 àèéìòù]+", " ", str(value.strip().lower()))
        value = re.sub(" +", " ", value)
        value = encode_emoji(value)

        action = "esci"
        if value != "esci":
            json, no_action = json_generator(value, tracker)
            if no_action != True:
                action = json['action']
            else:
                action = value

        if len(value) != 0:
            return {"action_1": action}
        else:
            dispatcher.utter_message("L'azione non può essere vuota.  \nInserisci l'azione.")
            return {"action_1": None}

    
# chiede l'azione quando viene inserito solo il tipo o l'entità
class ActionRetrieveActionOnlyAction(Action):

    def name(self):
        return "action_retrieve_action_only_action"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        save_conversation(tracker, "", 1)
        if tracker.get_slot("action_1") is not None:
            return[]
        conn, cursor = db_connection()
        conn_tables, cursor_tables, answers_table, questions_table = db_connection_tables()
        
        # estrazione global variables
        root, action_only_action, entity_type_only_action, entity_only_action, only_action, filter_string = global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action", "filter_string"], tracker)

        # estrazione dell'entità se è stata precedentemente inserita
        if entity_only_action != "" and entity_only_action != []:
            entita = entity_only_action.lower()
        else:
            if tracker.get_slot("name_1") is not None:
                entita = tracker.get_slot("name_1")
            else:
                entita = ""
                
        # se l'utente ha scritto "esci", salva la conversazione e azzera le variabili
        if (type(entita) == str and entita.lower() == "esci") or (type(entita) != str and "esci" in entita):
            message = "Uscito.\nCome posso aiutarti?"
            dispatcher.utter_message(message.replace("\n", "  \n"))
            
            # salvataggio della conversazione
            save_conversation(tracker, "no", 1)
            
            # azzeramento delle variabili globali
            slots_sets = update_global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", [], [], [], 0])
        
            conn.close()
            conn_tables.close()
            return slots_sets + [Restarted()]
        
        
        cursor_tables.execute("SELECT DISTINCT entities, faq_title FROM " + questions_table + filter_string.replace("AND", "WHERE"))
        entities = list(cursor_tables.fetchall())
        ### ENTITA' LEMMA ###
        cursor_tables.execute("SELECT DISTINCT entities_lemma, faq_title FROM " + questions_table + filter_string.replace("AND", "WHERE"))
        entities_lemma = list(cursor_tables.fetchall())
        entities = list(set(entities+entities_lemma)) # toglie doppioni con il set, poi torna List
        entities.sort() #ordinamento
        
        # estrae i sinonimi dell'entità per trovare più azioni possibili da suggerire
        entita_sinonimi = set()
        entita_sinonimi.add(entita)
        cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + entita + "'%\"")
        sinonimi = list(cursor.fetchall())
        if len(sinonimi) > 0:
            sinonimi = sinonimi[0][0]
            for s in eval(sinonimi):
                entita_sinonimi.add(s)
        
        # suggerisce le azioni che hanno entità uguale/sinonimi
        actions_set = set()
        faq_title_set = set() # se trova più azioni ma relativi a una sola faq, sceglie lei
        for ent in entities:
            e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))
            e_faq_title = str(ent[1])
            if str(e['entities']).lower() != "none":
                for e1 in eval(e['entities']):
                    if e1["entity"].lower() in entita_sinonimi and e["action"].lower() != "none":
                        actions_set.add(e["action"].lower())
                        faq_title_set.add(e_faq_title.lower())

        # se trova più azioni ma relativi a una sola faq, sceglie lei
        if len(faq_title_set) == 1:
            conn.close()
            conn_tables.close()
            return[SlotSet("action_1", list(actions_set)[0])]

        message = "Che cosa vuoi fare in particolare?\n"
        actions_set_with_synonyms = set()
        global ignored_verbs
        for t in actions_set:
            if t != "" and t != "none" and t not in actions_set_with_synonyms:
                message = message + "- " + t + "\n"
                
            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + t + "'%\"")
            sinonimi = cursor.fetchall()
            if len(sinonimi) > 0:
                sinonimi = eval(sinonimi[0][0])
                for s in sinonimi:
                    actions_set_with_synonyms.add(s)
            else:
                actions_set_with_synonyms.add(t)
                
        message = message + "(Oppure digita \"esci\" per uscire)"
        dispatcher.utter_message(message.replace("\n", "  \n"))
        
        conn.close()
        conn_tables.close()

        return[]



# richiesa dell'email per essere contattato da un operatore
class EmailForm(FormAction):

    def name(self):
        return "email_form"
    
    @staticmethod
    def required_slots(tracker):
        email = global_variables(["email_slot"], tracker)
        if email == "":
            return ["email"]
        else:
            return[]
    
    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        return { "email": [ self.from_text(intent=None) ] }
    
    def submit(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> List[Dict]:
        return []
    
    def validate_email(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> Dict[Text, Any]:
        db_connection_last_interaction()
        
        if re.search("^[a-zA-Z0-9]+[._-]*[a-zA-Z0-9]+@[a-zA-Z]+[.-]*[a-zA-Z]+[.][a-zA-Z]{2,3}$", value.replace(" ", "")):
            slots_sets = update_global_variables(["email_slot"], [value.replace(" ", "")])
            return {"email": value.replace(" ", ""), "email_slot": value.replace(" ", "")}
        else:
            dispatcher.utter_message("Inserisci un indirizzo email valido.")
            return {"email": None}

        

# salva nel db l'email e tutta la conversazione per essere poi contattato da un operatore
class ActionSaveEmail(Action):

    def name(self):
        return "action_save_email"

    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        conn, cursor = db_connection()
        
        # salvare email con conversazione
        email = global_variables(["email_slot"], tracker)
        
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
                if e['text'] == "Come posso aiutarti?" or "\nCome posso aiutarti?" in e['text']:
                    messages = user + e['text'] + ";;;"
                    events = str(e) + ";;;"
                else:
                    messages = messages + user + e['text'] + ";;;"

        messages = encode_emoji(messages)
        messages = messages.replace(";;;", "\n\n").strip()
        events = encode_emoji(events)
        events = events.replace(";;;", "\n\n").strip()
        
        cursor.execute("INSERT INTO rasa_assistenza (messages, last_timestamp, events, email, sender_id) VALUES (\"" + messages.replace("\"", "'") + "\", \""+ str(last_timestamp) + "\", \"" + events.replace("\"", "'") + "\", '" + email + "', '" + str(tracker.sender_id) + "')")
        conn.commit()
        conn.close()
        
        return []



# Se l'utente ha chiesto data, ora e/o giorno, ritorna tutte e 3 le informazioni
class ActionDateTime(Action):

    def name(self):
        return "action_date_time"
    
    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        now = datetime.now(timezone('Europe/Berlin'))
        dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
        
        day_today = calendar.day_name[datetime.strptime(dt_string.split(" ")[0].replace("/", " "), '%d %m %Y').weekday()]
        days = {"Monday": "lunedì", "Tuesday": "martedì", "Wednesday": "mercoledì", "Thursday": "giovedì", "Friday": "Venerdì", "Saturday": "sabato", "Sunday": "domenica"}
        this_day = days[day_today]
        
        message = "Oggi è " + this_day + " " + dt_string.split(" ")[0] + " e sono le ore " + dt_string.split(" ")[1][:-3] + ".\nCome posso aiutarti?"
        dispatcher.utter_message(message.replace("\n", "  \n"))
        return [Restarted()]

    
##################################
########## SEGNALAZIONE ##########
##################################
# richiesa del testo relativo alla segnalazione da aprire
class AprireSegnalazioneTestoForm(FormAction):

    def name(self):
        return "aprire_segnalazione_testo_form"
    
    @staticmethod
    def required_slots(tracker):
        return ["aprire_segnalazione_testo"]
    
    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        return { "aprire_segnalazione_testo": [ self.from_text(intent=None) ] }
    
    def submit(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> List[Dict]:
        return []
    
    def validate_aprire_segnalazione_testo(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> Dict[Text, Any]:
        db_connection_last_interaction()
        
        if len(str(value).strip()) != 0:
            return {"aprire_segnalazione_testo": value}
        else:
            dispatcher.utter_message("La segnalazione non può essere vuota.  \nRipeti l'inserimento.")
            return {"aprire_segnalazione_testo": None}



# Salva nel database le informazioni relative alla segnalazione
class ActionSalvaSegnalazione(Action):

    def name(self):
        return "action_salva_segnalazione"
    
    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        conn, cursor = db_connection()
        
        email = global_variables(["email_slot"], tracker)
        segnalazione = tracker.get_slot("aprire_segnalazione_testo")
        if segnalazione.lower().strip() != "esci":
            segnalazione = encode_emoji(segnalazione)
            cursor.execute("INSERT INTO segnalazioni (email, segnalazione, sender_id) VALUES (\"" + email + "\", \""+ segnalazione + "\", '" + str(tracker.sender_id) + "')")
            conn.commit()
            dispatcher.utter_message("La segnalazione è stata completata, verrai contattato appena possibile.")
        else:
            dispatcher.utter_message("Segnalazione annullata.")
        conn.close()
        
        return



###################################
######### OPERATORE UMANO #########
###################################
# chiede il testo da mandare all'operatore umano
class TestoForm(FormAction):

    def name(self):
        return "testo_form"
    
    @staticmethod
    def required_slots(tracker):
        return ["testo"]
    
    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        return { "testo": [ self.from_text(intent=None) ] }
    
    def submit(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> List[Dict]:
        return []
    
    def validate_testo(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any], ) -> Dict[Text, Any]:
        db_connection_last_interaction()
        
        if len(str(value).strip()) != 0:
            return {"testo": value}
        else:
            dispatcher.utter_message("Il messaggio da inviare all'operatore non può essere vuoto.  \nRipeti l'inserimento.")
            return {"testo": None}


# chiede email e setta redis per iniziare la conversazione con l'operatore
class ActionOperatore(Action):

    def name(self):
        return "action_operatore"
    
    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        dispatcher.utter_message("A breve verrai contattato da un operatore (in ogni momento puoi terminare la chat digitando 'esci').  \n  \nScrivi ora il messaggio da inviare ad un nostro operatore ed attendi un suo riscontro, grazie.")
        
        global redis_ip
        global redis_port
        global redis_n_db
        
        # creazione connessione a redis
        if redis_ip == "":
            # nel db redis 0 c'è:
            # - "LAST_ID" contenente l'ultimo id assegnato ad un bot
            # - chiavi corrispondenti ai nomi dei bot e il valore indica il numero del database associato a quella chiave
            # - chiave con id clienti collegati e il valore indica il numero del database associato a quel cliente
            redis_connection_file = open("../../db_connections/REDIS_CONNECTIONS.json", "r")
            redis_connection = str(redis_connection_file.read())
            redis_connection_file.close()
            redis_ip = redis_connection.split('"')[1]
            redis_port = int(redis_connection.split('port:')[1].split('}')[0])
            bot_name = str(subprocess.check_output("pwd", shell=True)).split("/")[4] #/home/jovyan/work/nome
            redis_db = redis.Redis(host=redis_ip, port=redis_port, db=0, decode_responses=True)
            if redis_db.get(bot_name) is not None: # già presente
                redis_n_db = redis_db.get(bot_name)
                redis_db.set(str(tracker.sender_id), str(redis_n_db))
            else: # da aggiungere, e' la prima volta che tale bot entra qui
                # prende l'ultimo id assegnato e lo incrementa di uno
                last_id = 0
                # se c'e' gia' LAST_ID settato lo prende, altrimenti 4 righe dopo lo aggiunge settandolo a 0
                if redis_db.get("LAST_ID") is not None:
                    last_id = int(redis_db.get("LAST_ID"))
                redis_n_db = last_id + 1
                redis_db.set("LAST_ID", str(redis_n_db))
                # aggiunge il proprio id
                redis_db.set(bot_name, str(redis_n_db))
                redis_db.set(str(tracker.sender_id), str(redis_n_db))
        else:
            redis_db = redis.Redis(host=redis_ip, port=redis_port, db=0, decode_responses=True)
            redis_db.set(str(tracker.sender_id), str(redis_n_db))
                           
        # inserimento in redis degli ultimi 10 messaggi
        redis_db = redis.Redis(host=redis_ip, port=redis_port, db=redis_n_db, decode_responses=True)
        messages = []
        for e in list(tracker.events)[-1000:]:
            if "'text': " in str(e) and "'event': 'user'" in str(e):
                messages.append("CLIENTE:" + e['text'].replace("\n", ". ") + "\n")
            if "'text': " in str(e) and "'event': 'bot'" in str(e) and e['text'] is not None:
                messages.append("BOT:" + e['text'].replace("\n", ". ") + "\n")
        last_messages = messages[-10:]
        redis_db.set("STORIA:" + str(tracker.sender_id), str(last_messages))
        
        # crea CLIENTE:id con [ASSISTENZA_FIRST, 0] così in socketio.py entra nel if dedicato al primo messaggio di una serie
        redis_db.set("CLIENTE:" + str(tracker.sender_id), str(["ASSISTENZA_FIRST", 0]))
        
        # aggiunge a redis l'id del cliente 
        if redis_db.get("CLIENTI") is None or redis_db.get("CLIENTI") == "[]":
            redis_db.set("CLIENTI", str([tracker.sender_id]))
        else:
            clienti = eval(redis_db.get("CLIENTI"))
            clienti.append(tracker.sender_id)
            redis_db.set("CLIENTI", str(clienti))

        # variabile che indica l'indice dell'ultimo messaggio estratto dell'operatore
        redis_db.set("LAST_READ_OPERATORE:" + str(tracker.sender_id), 0)
        # variabile che indica l'indice dell'ultimo messaggio scritto dall'operatore
        redis_db.set("OPERATORE:" + str(tracker.sender_id), 0)
        
        return []


# aspetta un messaggio dell'operatore da mandare al cliente e controlla quando terminare la chat
class ActionAttesaOperatore(Action):

    def name(self):
        return "action_attesa_operatore"
    
    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        global redis_ip
        global redis_port
        global redis_n_db
        redis_db = redis.Redis(host=redis_ip, port=redis_port, db=redis_n_db, decode_responses=True)
        # se l'utente ha chiesto di uscire, termina
        message_number = int(eval(redis_db.get("CLIENTE:" + str(tracker.sender_id)))[1])
        messaggio_utente = redis_db.get("CLIENTE:" + str(tracker.sender_id) + ":" + str(message_number))
        if messaggio_utente.lower().strip() == "esci":
            message = fine_conversazione(False, tracker)
            message = message + "\n\n" + exit_after_operator(tracker)
            for m in message.split("\n\n"):
                dispatcher.utter_message(m)
            # azzeramento delle variabili globali
            slots_sets = update_global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", [], [], [], 0])
            return slots_sets + [SlotSet("action_1", None), SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("assertion", None), SlotSet("found_name", "false"), SlotSet("testo", None), Restarted()]

        # gestione del timer
        last_timestamp = redis_db.get("TIMESTAMP:" + str(tracker.sender_id))
        now_timestamp = time.time()
        elapsed_time = 0
        # se non c'è il timestamp, lo aggiunge al primo giro
        if last_timestamp is None:
            redis_db.set("TIMESTAMP:" + str(tracker.sender_id), now_timestamp)
        # controlla se il timer è scaduto e nel caso esce dall'assistenza
        else:
            elapsed_time = now_timestamp - float(last_timestamp)
            if elapsed_time > 300:
                message = fine_conversazione(True, tracker) # timer
                message = message + "\n\n" + exit_after_operator(tracker)
                for m in message.split("\n\n"):
                    dispatcher.utter_message(m)
                # azzeramento delle variabili globali
                slots_sets = update_global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", [], [], [], 0])
                return slots_sets + [SlotSet("action_1", None), SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("assertion", None), SlotSet("found_name", "false"), SlotSet("testo", None), Restarted()]

        # se l'operatore ha risposto, l'indice dell'ultimo messaggio e l'indice dell'ultimo messaggio LETTO sono diversi
        index_chat_operatore = "OPERATORE:" + str(tracker.sender_id)
        index_last_message_operatore = int(redis_db.get(index_chat_operatore))
        last_read_operator_message = int(redis_db.get("LAST_READ_OPERATORE:" + str(tracker.sender_id)))
        if last_read_operator_message != index_last_message_operatore:
            message = ""
            for i in range(last_read_operator_message + 1, index_last_message_operatore + 1):
                message = message + "\n\n" + str(redis_db.get(index_chat_operatore + ":" + str(i)))
            redis_db.set("LAST_READ_OPERATORE:" + str(tracker.sender_id), index_last_message_operatore)

            # se l'operatore ha chiesto di uscire, e c'è un solo messaggio, termina
            if message.lower().strip() == "esci":
                message = fine_conversazione(False, tracker)
                message = message + "\n\n" + exit_after_operator(tracker)
                for m in message.split("\n\n"):
                    dispatcher.utter_message(m)
                # azzeramento delle variabili globali
                slots_sets = update_global_variables(["root", "action_only_action", "entity_type_only_action", "entity_only_action", "only_action"], ["", [], [], [], 0])
                return slots_sets + [SlotSet("action_1", None), SlotSet("name_1", None), SlotSet("type_1", None), SlotSet("assertion", None), SlotSet("found_name", "false"), SlotSet("testo", None), Restarted()]
            # se l'operatore ha chiesto di uscire, ma ci sono più messaggi, termina al giro successivo
            messages = message.lower().strip().split("\n\n")
            if "esci" in messages:
                redis_db.set(index_chat_operatore + ":" + str(index_last_message_operatore + 1), "esci")
                redis_db.set(index_chat_operatore, index_last_message_operatore + 1)
                redis_db.set("LAST_READ_OPERATORE:" + str(tracker.sender_id), index_last_message_operatore)
            
            # ritorna i messaggi multipli dell'operatore singolarmente
            for m in messages:
                if m != "esci":
                    dispatcher.utter_message(m.replace("\n", "  \n"))

            now_timestamp = time.time()
            redis_db.set("TIMESTAMP:" + str(tracker.sender_id), now_timestamp)

        return [FollowupAction("action_attesa_operatore")]



# Se il bot è stato d'aiuto, chiede una mail per migliorare il servizio (se non è già stata inserita)
class ActionInsertEmail(Action):

    def name(self):
        return "action_insert_email"
    
    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        email = global_variables(["email_slot"], tracker)
        assertion = tracker.get_slot("assertion").lower()
        message = ""

        if assertion != "no":
            if email == "":
                message = "Sono felice di esserti stato utile! Inserisci un indirizzo email al fine di migliorare questo servizio.\n"
            else:
                message = "Sono felice di esserti stato utile!\n"
        else:
            if email == "":
                message = "Inserisci un indirizzo email per essere ricontattato appena possibile.\n"
            else:
                message = "Verrai ricontattato appena possibile all'indirizzo email inserito precedentemente.\n"
        dispatcher.utter_message(message.replace("\n", "  \n"))

        return



# Se viene richiesta l'assistenza, chiede una mail nel caso non ci fossero operatori (se non è già stata inserita)
class ActionEmailOperatore(Action):

    def name(self):
        return "action_email_operatore"
    
    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        email = global_variables(["email_slot"], tracker)

        if email == "":
            message = "Tra un momento potrai scrivere ad un operatore.\nLascia la tua email per essere ricontattato nel caso in cui non ci fossero operatori disponibili.\n"
            dispatcher.utter_message(message.replace("\n", "  \n"))

        return



# Se viene richiesta l'assistenza, chiede una mail nel caso non ci fossero operatori (se non è già stata inserita)
class ActionAprireSegnalazioneEmail(Action):

    def name(self):
        return "action_aprire_segnalazione_email"
    
    def run(self, dispatcher, tracker, domain):
        db_connection_last_interaction()
        email = global_variables(["email_slot"], tracker)
        message = ""

        if email == "":
            message = "Inserisci un indirizzo email per poter aprire la segnalazione.\n"
        else:
            message = "Per aprire la segnalazione verrà utilizzato l'indirizzo email inserito precedentemente.\n"
        dispatcher.utter_message(message.replace("\n", "  \n"))

        return