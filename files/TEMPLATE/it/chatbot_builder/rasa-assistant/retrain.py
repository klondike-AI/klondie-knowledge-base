"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

from datetime import datetime
from Utils import *
import MySQLdb
import spacy
import time
import sys
import re
import os



#######################
##### Connessioni #####
#######################
start_retrain = datetime.now()
file = open("../../db_connections/DB_CONNECTIONS.json", "r")
dati_connessione = str(file.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn = eval("MySQLdb.connect(" + dati_connessione + ")")
file.close()
cursor = conn.cursor()

file_connessione = open("../../db_connections/DB_CONNECTIONS_TABLES.json", "r")
dati_connessione = str(file_connessione.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn_tables = eval("MySQLdb.connect(" + dati_connessione.split(", answers_table=")[0] + ")")
file_connessione.close()
cursor_tables = conn_tables.cursor()
answers_table = dati_connessione.split("\", answers_table=\"")[1].split("\", questions_table=")[0]
questions_table = dati_connessione.split("\", questions_table=\"")[1].split("\"")[0]

# contiene i verbi/azioni da ignorare (personalizzabile)
ignored_verbs = ["avere", "essere", "volere", "potere", "riuscire", "fare", "piacere", "sapere", "dovere", "interessare", "aiutare", "servire"]
# contiene i verbi/azioni che spaCy non riconosce (personalizzabile)
spacy_ignored_verbs = ["fare", "stampare"]
# contiene le desinenze di verbi/azioni mascherati da sostantivi (es. configurazione -> configurare)
finali_verbi_sostantivi = ["mento", "menti", "zione", "zioni", "tura", "ture"]


###################################
##### AGGIUNTA RIGA NEL DB ########
###################################
# aggiunge una riga nel db con il nome del nuovo modello
# train_complete e spacy_train_complete sono inizialmente a NULL
model_index = sys.argv[1]
model_name = "model_directory_" + str(model_index)
cursor.execute("INSERT INTO rasa_faq_models (name, inizio_train) VALUES ('" + str(model_name) + "', '" + str(start_retrain) + "')")
conn.commit()
# ogni tot secondi aggiorna lo stato di avanzamento nel db
os.chdir("../../customer_chatbot/rasa-assistant")
os.system("touch train_output.txt")
os.chdir("../../chatbot_builder/rasa-assistant/")
os.system("python percentuale_training.py " + str(model_index) + "&") # in background


###########################
##### Flag Assistenza #####
###########################
# se flag_assistenza = 1, si tiene tutta la parte dell'assistenza
# se flag_assistenza = 2, nessuna assitenza ma si chiede la mail se il chatbot non è d'aiuto
f_assistenza = sys.argv[2]
flag_assistenza = str(f_assistenza)


######################################################################
##### Aggiornamento delle colonne "entities" ed "entities_lemma" #####
######################################################################
nlp = None
try:
    nlp = spacy.load("../../model/model_NER/model")
except:
    nlp = spacy.load("../../standard_model_it/it_core_news_md/it_core_news_md-2.3.0")
json_generator(conn, cursor, cursor_tables, conn_tables, questions_table, nlp, ignored_verbs, spacy_ignored_verbs, finali_verbi_sostantivi)
    
    
    
###############################
##### RETRAIN DI SPACY ########
###############################
cursor.execute("SELECT id FROM rasa_faq_models WHERE spacy_train_complete LIKE 'True'")
spacy_trained = list(cursor.fetchall())
if len(spacy_trained) > 0:
    cursor.execute("UPDATE rasa_faq_models SET spacy_train_complete = 'True' WHERE id = " + str(model_index))
    conn.commit()
else:
    filename = "retrain_spacy.py"
    os.system("python " + filename + " &") # in background



#####################################
##### Generazione file "nlu.md" #####
#####################################
# Storie informative, saluti, chiacchiere
nlu = nlu_generator(cursor, cursor_tables, questions_table, flag_assistenza)



#########################################
##### Generazione file "stories.md" #####
#########################################
stories = stories_generator(flag_assistenza)



#########################################
##### Generazione file "domain.yml" #####
#########################################
domain_intent, domain_actions, domain_utter, domain_form, domain_slot = domain_generator(flag_assistenza)



################################################
##### Generazione intento generico e testi #####
################################################
# intento generico per tutte le faq
nlu = nlu + "## intent:intent_faq\n"

# creazione delle storie relative ad ogni faq_title
cursor_tables.execute("SELECT DISTINCT faq_title FROM " + questions_table)
faq_titles = list(cursor_tables.fetchall())
for f in faq_titles:
    # per il nome si usa la prima faq con quel faq_title
    cursor_tables.execute("SELECT frase, faq_title, entities FROM " + questions_table + " WHERE faq_title = \"" + f[0] + "\" LIMIT 1")
    question_list = list(cursor_tables.fetchall())
    faq_title = question_list[0][1].lower()

    # estrazione di azione ed entità dalla prima faq con un determinato faq_title
    entities = []
    azione = eval(question_list[0][2].replace("'[", "\"[").replace("]'", "]\""))["action"]
    for i in question_list:
        entita = eval(eval(i[2].replace("'[", "\"[").replace("]'", "]\""))["entities"])
        if entita is not None:
            for ent in entita:
                if ent not in entities:
                    entities.append(ent)
    # se non ha entità, si mette "entities": "None"
    if str(entities) != "[]":
        entities = {"action": azione, "entities": str(entities)}
    else:
        entities = {"action": azione, "entities": "None"}


    # prende tutte le frasi con la stessa "faq_title" e le aggiunge all'intento generico in NLU
    cursor_tables.execute("SELECT frase, faq_title, entities FROM " + questions_table + " WHERE faq_title = \"" + faq_title + "\"")
    quests = list(cursor_tables.fetchall())

    # Si aggiungono le frasi complete (con qualche alternativa in più) al file NLU
    for q1 in quests:
        # si aggiunge la frase completa
        nlu = nlu + "- " + q1[0].lower() + "\n"
        # si aggiunge il verbo della frase
        nlu = nlu + "- " + entities["action"] + "\n"

        # questo pezzo di codice viene eseguito per ogni entità, così da avere più frasi alternative in NLU
        tripla = eval(q1[2].replace("'[", "\"[").replace("]'", "]\""))
        if eval(tripla['entities']) is not None:
            for entity in eval(tripla['entities']):
                if tripla['action'].lower() != "none" and entity['entity'].lower() != "none":
                    # si aggiunge la frase "verbo entità" ad NLU
                    this_faq_entity = "- " + tripla['action'] + " " + entity['entity'] + "\n"
                    if this_faq_entity not in nlu:
                        nlu = nlu + this_faq_entity
conn_tables.close()



#############################
##### Scritture su file #####
#############################
# controlla che non ci siano frasi uguali in intenti diversi
# ripulisce da frasi vuote
nlu = nlu.replace("- \n", "")
nlu_temp = ""
for n in nlu.split("\n"):
    if (n + "\n") not in nlu_temp:
        nlu_temp = nlu_temp + n + "\n"
nlu = nlu_temp

### Scrittura sul file nlu.md
f = open("../../customer_chatbot/rasa-assistant/data/nlu.md", "w")
nlu = re.sub(' +', ' ', nlu)
f.write(nlu.replace("/", ""))
f.close()

### Scrittura sul file stories.md
f = open("../../customer_chatbot/rasa-assistant/data/stories.md", "w")
f.write(stories.replace("/", ""))
f.close()


### Scrittura sul file domain.yml
domain = domain_intent + domain_actions + domain_slot + domain_utter + domain_form + """
session_config:
  carry_over_slots_to_new_session: true
  session_expiration_time: 0"""
f = open("../../customer_chatbot/rasa-assistant/domain.yml", "w")
f.write(domain.replace("#", ""))
f.close()



#######################################
##### RETRAIN COMPLETO NLU + CORE #####
#######################################
project = "../../customer_chatbot/rasa-assistant"
os.chdir(project)
config = "config.yml"
training_files = "data/"
domain = "domain.yml"
output = "models/"

# eliminazione modelli vecchi (tiene solo i due piu' recenti)
os.chdir("./models/")
os.system("rm -r ./*")
os.chdir("../")

# esegue il train completo nlu + core
#model_path = rasa.train(domain, config, [training_files], output)
os.system("unbuffer rasa train --force | tee train_output.txt")
time.sleep(30)
os.system("rm train_output.txt")
os.chdir("../../chatbot_builder/rasa-assistant/")



######################################
##### ATTESA AGGIORNAMENTO SPACY #####
######################################
while True:
    # ogni 15 secondi controlla se è terminato il retrain di spaCy
    time.sleep(15)
    cursor.execute("SELECT spacy_train_complete FROM rasa_faq_models WHERE id = " + str(model_index))
    spacy_train_complete = str(cursor.fetchall()[0][0])
    if spacy_train_complete == "True":
        # quando ha completato il retrain del nuovo modello spacy lo carica per usare questo aggiornato
        try:
            nlp = spacy.load("../../model/model_NER/model")
        except:
            nlp = spacy.load("../../standard_model_it/it_core_news_md/it_core_news_md-2.3.0")
        break
    

### Aggiornamento della colonna "train_complete" per avvisare che il train completo è terminato
end_retrain = datetime.now()
cursor.execute("UPDATE rasa_faq_models SET train_complete = 'True' WHERE id = " + str(model_index))
conn.commit()
cursor.execute("UPDATE rasa_faq_models SET status = 'Allenamento Completato', fine_train = '" + str(end_retrain) + "' WHERE id = " + str(model_index))
conn.commit()
conn.close()