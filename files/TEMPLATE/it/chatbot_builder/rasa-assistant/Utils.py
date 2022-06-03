"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

import re



#############################################
############## FIND WHOLE WORD ##############
#############################################
### Funzione che verifica se la parola "w" è contenuta in una frase, senza essere sottostringa di un'altra parola
# INPUTS:
# - w: parola da ricercare all'interno della frase
# OUTPUTS:
# - return: "True" oppure "False" se la parola è contenuta o meno
def findWholeWord(w):
    return re.compile(r'\b({0})\b'.format(w), flags=re.IGNORECASE).search



############################################
############### REPLACE WORD ###############
############################################
### Funzione che rimpiazza "findWord" con "replaceWord" in "text", ma non le parole che contengono "findWord"
# INPUTS:
# - text: testo sul quale eseguire la sostituzione
# - findWord: parola da rimpiazzare nella frase
# - replaceWord: parola da inserire nella frase
# OUTPUTS:
# - return: frase con la parola rimpiazzata
def replace_word(text, findWord, replaceWord):
    # se "findWord" è composta da più parole, viene fatto il replace standard delle stringhe
    if len(findWord.split(" ")) < 1:
        return ' '.join(replaceWord if word == findWord else word for word in text.split(' '))
    else:
        return text.replace(findWord, replaceWord)



####################################################
############### TROVA SPACY ENTITIES ###############
####################################################
### Funzione che prende tutte le {entita:tipo}, ed i relativi sinonimi, dalla tabella "entities"
# INPUTS:
# - conn: connessione al database di supporto
# - cursor: cursore per interrogare il database di supporto
# OUTPUTS:
# - spacy_entities: dizionario {entita:tipo} con tutte le entità presenti
def trova_spacy_entities(conn, cursor):    
    spacy_entities = {}
    # estrazione delle entità presenti nella tabella "entities"
    cursor.execute("SELECT entity, entity_type FROM entities")
    entita = list(cursor.fetchall())
    if len(entita) > 0:
        for ent in entita:
            entity = str(ent[0]).lower()
            entity_type = str(ent[1]).lower()
            # estrazione dei sinonimi relativi alle entità estratte
            cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + entity + "'%\"")
            sinonimi = list(cursor.fetchall())
            if len(sinonimi) > 0:
                sinonimi = sinonimi[0][0]
                for s in eval(sinonimi):
                    entity = str(s).lower()
                    spacy_entities[entity] = str(entity_type).lower() # dizionario {entita:tipo}
            else:
                entity = str(entity).lower()
                spacy_entities[entity] = str(entity_type).lower() # dizionario {entita:tipo}
    return spacy_entities



#########################################
############### GET LEMMA ###############
#########################################
### Funzione che ritorna la tripla con l'entità lemmatizzata
# INPUTS:
# - triple: tripla contenente azione, entità e tipi
# - nlp: processore di linguaggio naturale (spaCy) per trovare il lemma di una parola
# OUTPUTS:
# - return: tripla lemmatizzata
def get_lemma(triple, nlp):
    if "'entities': 'None'" in triple:
        return triple
    lemmatized = ""
    for s in triple.split("'}"):
        sub_entity = re.search('\'entity\': \'(.*)', s)
        if sub_entity:
            nlp_lemma = nlp(sub_entity.group(1))
            lemma = ""
            for l in nlp_lemma:
                lemma = lemma + l.lemma_ + " "
            lemmatized = lemmatized + s.replace("'entity': '" + sub_entity.group(1), "'entity': '") + lemma.strip() + "'}"
        else:
            lemmatized = lemmatized + s + "'}" 
    lemmatized = lemmatized[:-2]
    return lemmatized



##############################################
############### JSON GENERATOR ###############
##############################################
### Funzione che aggiorna le colonne "entities" ed "entities_lemma" nella tabella delle faq
# INPUTS:
# - conn: connessione al database di supporto
# - cursor: cursore per interrogare il database di supporto
# - conn_tables: connessione al database delle faq
# - cursor_tables: cursore per interrogare il database delle faq
# - questions_table: nome della tabella contenente le domande relative alle faq
# - nlp: processore di linguaggio naturale (spaCy) per trovare il lemma di una parola
# - ignored_verbs: verbi che devono essere ignorati (a meno che non siano gli unici nella frase)
# - spacy_ignored_verbs: verbi che spaCy non riconosce
# - finali_verbi_sostantivi: desinenze dei verbi mascherati da sostantivi
# OUTPUTS:
# - return: non ritorna nulla, salva direttamente nelle colonne "entities" ed "entities_lemma" nella tabella delle faq
def json_generator(conn, cursor, cursor_tables, conn_tables, questions_table, nlp, ignored_verbs, spacy_ignored_verbs, finali_verbi_sostantivi):
    # desinenze dei verbi con pronomi che spaCy non riconosce
    endings6 = ["glielo", "gliela", "glieli", "gliele", "gliene"]
    endings4 = ["telo", "tela", "teli", "tele", "melo", "mela", "meli", "mele"]
    endings3 = ["gli"]
    endings2 = ["si", "mi", "lo", "li", "la", "le", "ci", "ne", "ti", "vi", "me", "te", "ce", "ve"]
        
    cursor_tables.execute("SELECT id, frase FROM " + questions_table)
    questions = list(cursor_tables.fetchall())
    for q in questions:
        # json iniziale che conterrà l'intento e le eventuali entità della frase (con i relativi tipi)
        json = {"action": "None", "entities": "None"}
        entities = []
        
        frase = q[1].replace("'", " ").lower()
        doc = nlp(frase)
        
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
        
        # ricerca dell'intento all'interno della frase
        for t in doc:
            # Se la root estratta da spaCy È un verbo, si prende quella
            if t.dep_ == "ROOT" and (t.pos_ == "VERB" or t.pos_ == "AUX") and t.lemma_.lower() not in ignored_verbs and (t.lemma_.lower()[-3:] in ["are", "ere", "ire"] or t.lemma_.lower()[-4:] in ["arre", "orre", "urre"]):
                found_action = True
                contains_verb = True
                json["action"] = t.lemma_.lower()
                    
            # Se la root estratta da spaCy NON È un verbo, ma nella frase è presente un verbo, si prende quello
            elif (t.pos_ == "VERB" or t.pos_ == "AUX") and found_action == False and (t.lemma_.lower()[-3:] in ["are", "ere", "ire"] or t.lemma_.lower()[-4:] in ["arre", "orre", "urre"]) and t.lemma_.lower() not in ignored_verbs:
                json["action"] = t.lemma_.lower()
                contains_verb = True
            
            # Se la root estratta da spaCy NON È un verbo e non trova nessun altro verbo, si tolgono i pronomi (desinenze) alla fine della parola e si verifica se è un verbo 
            elif found_action == False and contains_verb == False:
                if t.text[-6:] in endings6:
                    text = t.text[:-6] + "e"
                    doc_text = nlp(text)
                    if (doc_text[0].pos_ == "VERB" or doc_text[0].pos_ == "AUX") and (doc_text[0].lemma_.lower()[-3:] in ["are", "ere", "ire"] or doc_text[0].lemma_.lower()[-4:] in ["arre", "orre", "urre"]) and doc_text[0].lemma_.lower() not in ignored_verbs:
                        json["action"] = doc_text[0].lemma_.lower()
                        contains_verb = True
                elif t.text[-4:] in endings4:
                    text = t.text[:-4] + "e"
                    doc_text = nlp(text)
                    if (doc_text[0].pos_ == "VERB" or doc_text[0].pos_ == "AUX") and (doc_text[0].lemma_.lower()[-3:] in ["are", "ere", "ire"] or doc_text[0].lemma_.lower()[-4:] in ["arre", "orre", "urre"]) and doc_text[0].lemma_.lower() not in ignored_verbs:
                        json["action"] = doc_text[0].lemma_.lower()
                        contains_verb = True
                elif t.text[-3:] in endings3:
                    text = t.text[:-3] + "e"
                    doc_text = nlp(text)
                    if (doc_text[0].pos_ == "VERB" or doc_text[0].pos_ == "AUX") and (doc_text[0].lemma_.lower()[-3:] in ["are", "ere", "ire"] or doc_text[0].lemma_.lower()[-4:] in ["arre", "orre", "urre"]) and doc_text[0].lemma_.lower() not in ignored_verbs:
                        json["action"] = doc_text[0].lemma_.lower()
                        contains_verb = True
                elif t.text[-2:] in endings2:
                    text = t.text[:-2] + "e"
                    doc_text = nlp(text)
                    if (doc_text[0].pos_ == "VERB" or doc_text[0].pos_ == "AUX") and (doc_text[0].lemma_.lower()[-3:] in ["are", "ere", "ire"] or doc_text[0].lemma_.lower()[-4:] in ["arre", "orre", "urre"]) and doc_text[0].lemma_.lower() not in ignored_verbs:
                        json["action"] = doc_text[0].lemma_.lower()
                        contains_verb = True
            # Se la root estratta da spaCy NON È un verbo e non trova altri verbi neanche con i pronomi, si tiene un verbo da ignorare (se presente)
            # IGNORE_VERB
            if (t.pos_ == "VERB" or t.pos_ == "AUX") and contains_verb == False and (t.lemma_.lower()[-3:] in ["are", "ere", "ire"] or t.lemma_.lower()[-4:] in ["arre", "orre", "urre"]) and t.lemma_.lower() in ignored_verbs:
                ignore_verb = t.lemma_.lower()
                contains_ignore_verb = True
                if ignore_verb == "essere" or ignore_verb == "avere":
                    ignore_verb = "avere informazioni"
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
                        verbo_sostantivo = str(t.text).replace(f, "re")
                        if verbo_sostantivo[-3:] == "ure":
                            verbo_sostantivo = verbo_sostantivo[:-3] + "urre"

            
            # si riporta se la frase contiene un verbo ausiliario, utilizzando la relativa variabile booleana
            if t.lemma_.lower() == "essere":
                contains_essere = True
            if t.lemma_.lower() == "avere":
                contains_avere = True

        # Se spaCy non rileva verbi, ma è presente il verbo "essere", si prende quello
        if contains_verb == False and contains_essere == True:
            root = "avere informazioni"
        # Se spaCy non rileva verbi, non è presente il verbo "essere" ma è presente il verbo "avere", si prende quello
        elif contains_verb == False and contains_essere == False and contains_avere == True:
            root = "avere informazioni"
        # Se spaCy non rileva verbi e trova solo "ignore_verb", lo utilizza come root
        if contains_verb == False and contains_ignore_verb == True:
            json["action"] = ignore_verb
        # Se spaCy non rileva verbi e trova solo un verbo mascherato da sostantivo, lo utilizza come root
        elif contains_verb == False and contains_verbo_sostantivo == True:
            json["action"] = verbo_sostantivo
        # Se spaCy non rileva nessuna tipologia di verbo, utilizza come root "avere informazioni"
        elif contains_verb == False and contains_ignore_verb == False:
            json["action"] = "avere informazioni"
            
        # Se nella frase è presente solamente il verbo "avere" oppure il verbo "essere", si utilizza come intento "avere informazioni"
        if json["action"] == "None" and root == "avere informazioni":
            json["action"] = "avere informazioni"
        # Se nella frase non è presente alcun verbo, si utilizza di default l'intento "avere informazioni"
        elif json["action"] == "None":
            json["action"] = "avere informazioni"
            
        # aggiunge eventuali entità composte da più parole che spaCy non trova
        # le cerca confrontando le parole della frase con le entità contenute nel vettore "spacy_entities"
        # il vettore "spacy_entities" viene estratto da "faq_questions" e corrisponde a tutte le entità distinte nel DB
        domanda = re.sub("[^a-zA-Z0-9 àèéìòù]+", " ", frase)
        domanda = re.sub(" +", " ", domanda)

        # frase composta dai lemmi di ciascuna parola
        frase_lemma = ""
        doc_domanda = nlp(domanda.lower().strip())
        for d in doc_domanda:
            frase_lemma = frase_lemma + d.lemma_ + " "

        # estrazione di tutte le entità (e relativi sinonimi) dal database
        spacy_entities = trova_spacy_entities(conn, cursor)
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
            # si cercano i lemmi delle entità nella frase composta dai lemmi di ciascuna parola
            else:
                # si genera il lemma dell'entità (che può essere composta da più parole)
                entita_lemma = ""
                for s1 in s.strip().lower().split(" "):
                    nlp_s = nlp(s1)
                    entita_lemma = entita_lemma + nlp_s[0].lemma_ + " "
                entita_lemma = entita_lemma.strip()
                # si cerca il lemma dell'entità nella frase composta dai lemmi delle parole
                if findWholeWord(str(entita_lemma))(frase_lemma.strip().lower()) != None:
                    # se il lemma dell'entità è presente nella frase composta da lemmi
                    # si estrae dalla frase l'entità senza lemma e si salva con il relativo tipo
                    entita = ""
                    first_pos = len(frase_lemma.split(entita_lemma)[0].split(" ")) - 1
                    for i in range(first_pos, first_pos + len(entita_lemma.split(" "))):
                        entita = entita + domanda.split(" ")[i] + " "
                    entita = entita.strip()
                    new_entity = "{'entity_type': '" + tipo + "', 'entity': '" + entita + "'}"
                    if new_entity not in entities:
                        entities.append(new_entity)

        # le entità vengono ordinate
        entities.sort()
        if str(entities) != "[]":
            json["entities"] = str(entities).replace('"{', '{').replace('}"', '}')
        
        # inserimento delle entità nella colonna "entities" della tabella "faq_questions"
        cursor_tables.execute("UPDATE " + questions_table + " SET entities = \"" + str(json).replace('"', "'") + "\" WHERE id = " + str(q[0]))
        conn_tables.commit()
        # inserimento dei lemmi delle entità nella colonna "entities_lemma" della tabella "faq_questions"
        json_lemma = get_lemma(str(json).replace('"', "'"), nlp)
        cursor_tables.execute("UPDATE " + questions_table + " SET entities_lemma = \"" + str(json_lemma) + "\" WHERE id = " + str(q[0]))
        conn_tables.commit()

    return



#############################################
############### NLU GENERATOR ###############
#############################################
### Funzione che genera il contenuto del file "nlu.md", ovvero intenti e testi di Rasa
# INPUTS:
# - cursor: cursore per interrogare il database di supporto
# - cursor_tables: cursore per interrogare il database delle faq
# - questions_table: nome della tabella contenente le domande relative alle faq
# - flag_assistenza: 1 se è settata l'assistenza dell'operatore umano e possibilità di aprire segnalazioni, 1 solo operatore umano, 0 altrimenti
# OUTPUTS:
# - nlu: stringa che rappresenta il contenuto del file "nlu.md" con intenti e testi per Rasa
def nlu_generator(cursor, cursor_tables, questions_table, flag_assistenza):
    nlu = """## intent:intent_saluti
- Ciao
- ciaoo
- Salve
- Salve!
- Buongiorno
- buon giorno
- Buon Pomeriggio
- Buonasera
- buona sera
- hey
- hey!
- ehilà
- hey ciao
- Chi sei?
- chi sei tu?
- tu chi sei?\n"""
    # estrazione delle linee per il saluto inziale
    cursor_tables.execute("SELECT DISTINCT linea FROM " + questions_table + " WHERE linea IS NOT NULL")
    linee_db = list(cursor_tables.fetchall())
    linee = set()
    for linea in linee_db:
        linea = linea[0].split("-")
        for l in linea:
            if len(l) > 0:
                linee.add(l)
    for linea in linee:
        nlu = nlu + "- ciao #" + linea + "#\n"
    nlu = nlu + """\n
## intent:giorno_ora
- che ore sono?
- che giorno è oggi?
- quale è la data di oggi?
- data e ora

## intent:chitchat
- che tempo fa?
- che tempo farà?
- che tempo c'è?
- racconta una barzelletta
- mi racconti una barzelletta
- raccontami delle barzellette
- quanti anni hai?\n\n"""

    if flag_assistenza == "1":
        nlu = nlu + """## intent:u_operatore
- operatore
- persona
- assistenza
- parlare con un operatore
- parlare con una persona
- contattare operatore
- contattare l'assistenza
- scrivere ad un operatore
- passami un operatore
- passami una persona
- passami l'assistenza
- fammi parlare con un operatore
- voglio parlare con una persona
- voglio contattare l'assistenza
- voglio parlare con l'assistenza

## intent:aprire_segnalazione
- segnalazione
- aprire una segnalazione
- voglio aprire una segnalazione
- ticket
- aprire un ticket
- voglio aprire un ticket
- fare una segnalazione
- voglio fare una segnalazione\n\n"""

    nlu = nlu + """## intent:intent_cosa_posso_fare
- Cosa posso fare?
- Cosa puoi fare?
- Cosa sai fare?
- cosa fai?
- tu cosa fai?
- Che cosa posso fare?
- Che cosa sai fare?
- Quali sono le tue capacità?
- help
- aiuto
- aiutami
- problema
- cosa posso chiederti?
- Che cosa posso chiedere?\n\n"""

    nlu_entities = """## intent:intent_entitytype_entity\n"""
    nlu_entities_set = set()

    cursor_tables.execute("SELECT DISTINCT entities FROM " + questions_table)
    entities = list(cursor_tables.fetchall())
    for ent in entities:
        e = eval(ent[0].replace("'[", "\"[").replace("]'", "]\""))

        # creazione intento intent_entitytype_entity (+ sinonimi)
        entities = eval(e["entities"])
        if entities is not None:
            for e1 in entities:
                if e1['entity_type'] not in nlu_entities_set and len(e1['entity_type'].strip()) != 0 and e1['entity_type'] != "/":
                    nlu_entities_set.add(e1['entity_type'])
                    nlu_entities = nlu_entities + "- " + str(e1['entity_type']) + "\n"
                cursor.execute("SELECT words FROM synonyms WHERE words LIKE \"%'" + e1['entity'] + "'%\"")
                words = cursor.fetchall()
                if len(words) != 0:
                    sinonimi = eval(words[0][0])
                    for s in sinonimi:
                        if s not in nlu_entities_set and len(s.strip()) != 0 and len(e1['entity'].strip()) != 0 and e1['entity'] != 'None' and e1['entity'] != "/":
                            nlu_entities_set.add(s)
                            nlu_entities = nlu_entities + "- " + str(s) + "\n"
                else:
                    if e1['entity'] not in nlu_entities_set and len(e1['entity'].strip()) != 0 and e1['entity'] != "/":
                        nlu_entities_set.add(e1['entity'])
                        nlu_entities = nlu_entities + "- " + str(e1['entity']) + "\n"

    nlu = nlu + nlu_entities
    return nlu



#################################################
############### STORIES GENERATOR ###############
#################################################
### Funzione che genera il contenuto del file "stories.md", ovvero i percorsi del chatbot Rasa
# INPUTS:
# - flag_assistenza: 1 se è settata l'assistenza dell'operatore umano e possibilità di aprire segnalazioni, 1 solo operatore umano, 0 altrimenti
# OUTPUTS:
# - stories: stringa che rappresenta il contenuto del file "stories.md" con i percorsi del chatbot Rasa
def stories_generator(flag_assistenza):
    stories = """## faq
* intent_faq
  - action_set_action
> check_action

## faq_not_complete
> check_action
  - slot{"found_name":"false"}
  - action_retrieve_types
  - type_form
  - form{"name": "type_form"}
  - form{"name": null}
> check_types

## faq_complete
> check_action
  - slot{"found_name":"true"}
  - action_retrieve_faq
  - slot{"assertion": null}
> check_check_another_faq\n\n"""

    # Storia comune per tutti gli intenti: una volta scelto il tipo, si propongono i nomi e ci cerca la faq
    # Se nello slot del tipo c'è il nome dell'entità si procede all'estrazione della faq
    stories = stories + """## type_chosen
> check_types
  - action_retrieve_name
  - slot{"found_name":"false"}
  - name_form
  - form{"name": "name_form"}
  - form{"name": null}
  - action_retrieve_faq
  - slot{"assertion": null}
> check_check_another_faq

## type_name_chosen
> check_types
  - action_retrieve_name
  - slot{"found_name":"true"}
  - action_retrieve_faq
  - slot{"assertion": null}
> check_check_another_faq\n\n"""


    # Storie che hanno inizio scrivendo solamente l'azione
    stories = stories + """## check_another_faq_only_action
> check_check_another_faq_only_action
  - slot{"check_another_faq":"si"}
> check_new_faq_only_action

## new_faq_ok_only_action
> check_new_faq_only_action
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion":"si"}
  - action_retrieve_faq
  - slot{"assertion": null}
> check_problema_risolto

## new_faq_not_ok_only_action
> check_new_faq_only_action
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion":"no"}
  - action_exit
  - slot{"assertion": null}
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}

## no_check_another_faq_only_action
> check_check_another_faq_only_action
  - slot{"check_another_faq":"no"}
> check_problema_risolto\n\n"""

    # Storie che hanno inizio scrivendo solamente il tipo
    stories = stories + """## only_entitytype
* intent_entitytype_entity
  - action_set_action_type_only_action
  - action_retrieve_name_only_action
  - slot{"found_name":"false"}
  - name_form
  - form{"name": "name_form"}
  - form{"name": null}
  - action_retrieve_action_only_action
  - action_form
  - form{"name": "action_form"}
  - form{"name": null}
  - action_retrieve_faq
  - slot{"assertion": null}
> check_check_another_faq_only_action\n\n"""

    # Storie che hanno inizio scrivendo solamente l'entità
    stories = stories + """## only_entity
* intent_entitytype_entity
  - action_set_action_type_only_action
  - action_retrieve_name_only_action
  - slot{"found_name":"true"}
  - action_retrieve_action_only_action
  - action_form
  - form{"name": "action_form"}
  - form{"name": null}
  - action_retrieve_faq
  - slot{"assertion": null}
> check_check_another_faq_only_action\n\n"""

    # Storie per verificare se il bot ha risolto il problema
    # Se il problema non è risolto, si propone di lasciare un contatto per l'assistenza
    if flag_assistenza == "1":
        stories = stories + """## problema_risolto_si
> check_problema_risolto
  - utter_problema_risolto
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "si"}
  - action_insert_email
  - email_form
  - form{"name": "email_form"}
  - form{"name": null}
  - action_save_email
  - action_exit
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}

## problema_risolto_no
> check_problema_risolto
  - utter_problema_risolto
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "no"}
> check_assistenza

## assistenza_si
> check_assistenza
  - utter_assistenza
  - action_reset_assertion
  - slot{"assertion": null}
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "si"}
  - action_email_operatore
  - email_form
  - form{"name": "email_form"}
  - form{"name": null}
  - action_save_email
  - action_operatore
> check_operatore
  
## assistenza_no
> check_assistenza
  - utter_assistenza
  - action_reset_assertion
  - slot{"assertion": null}
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "no"}
  - action_insert_email
  - email_form
  - form{"name": "email_form"}
  - form{"name": null}
  - action_save_email
  - action_exit
  - slot{"assertion": null}
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}\n\n"""
    elif flag_assistenza == "2":
        stories = stories + """## problema_risolto_si
> check_problema_risolto
  - utter_problema_risolto
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "si"}
  - action_exit
  - slot{"assertion": null}
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}

## problema_risolto_no
> check_problema_risolto
  - utter_problema_risolto
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "no"}
  - action_insert_email
  - email_form
  - form{"name": "email_form"}
  - form{"name": null}
  - action_save_email
  - action_exit
  - slot{"assertion": null}
  - slot{"email": null}
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}\n\n"""
    else:
        stories = stories + """## problema_risolto_si
> check_problema_risolto
  - utter_problema_risolto
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "si"}
  - action_exit
  - slot{"assertion": null}
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}

## problema_risolto_no
> check_problema_risolto
  - utter_problema_risolto
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion": "no"}
  - action_exit
  - slot{"assertion": null}
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}\n\n"""


    # Storie per contattare un operatore umano tramite la chat
    if flag_assistenza == "1":
        stories = stories + """## operatore
* u_operatore
  - action_email_operatore
  - email_form
  - form{"name": "email_form"}
  - form{"name": null}
  - action_save_email
  - action_operatore
> check_operatore

## operatore_sì
> check_operatore
  - testo_form
  - form{"name": "testo_form"}
  - form{"name": null}
  - action_attesa_operatore
  - slot{"testo": null}
  - slot{"assertion": null}
  - slot{"found_name": "false"}\n\n"""

    # Storie comuni che non serve replicare per tutti gli intenti
    stories = stories + """## check_another_faq
> check_check_another_faq
  - slot{"check_another_faq":"si"}
> check_new_faq

## new_faq_ok
> check_new_faq
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion":"si"}
  - action_retrieve_faq
  - slot{"assertion": null}
> check_problema_risolto

## new_faq_not_ok
> check_new_faq
  - assertion_form
  - form{"name": "assertion_form"}
  - form{"name": null}
  - slot{"assertion":"no"}
  - action_exit
  - slot{"assertion": null}
  - slot{"check_another_faq": "no"}
  - slot{"found_name": false}

## no_check_another_faq
> check_check_another_faq
  - slot{"check_another_faq":"no"}
> check_problema_risolto

## saluti
* intent_saluti
  - action_extract_filter
  
## orario_giorno
* giorno_ora
  - action_date_time

## chitchat
* chitchat
  - utter_chitchat

## cosa_posso_fare
* intent_cosa_posso_fare
  - utter_cosa_posso_fare\n\n"""

    if flag_assistenza == "1":
        stories = stories + """## aprire_segnalazione
* aprire_segnalazione
  - action_aprire_segnalazione_email
  - email_form
  - form{"name": "email_form"}
  - form{"name": null}
  - utter_aprire_segnalazione_testo
  - aprire_segnalazione_testo_form
  - form{"name": "aprire_segnalazione_testo_form"}
  - form{"name": null}
  - action_salva_segnalazione
  - action_exit
  - slot{"aprire_segnalazione_testo": null}\n\n"""

    return stories



################################################
############### DOMAIN GENERATOR ###############
################################################
### Funzione che genera il contenuto del file "domain.yml", ovvero le dichiarazioni di intenti, azioni, form, slot e responses.
# INPUTS:
# - flag_assistenza: 1 se è settata l'assistenza dell'operatore umano e possibilità di aprire segnalazioni, 1 solo operatore umano, 0 altrimenti
# OUTPUTS:
# - domain: stringa che rappresenta il contenuto del file "domain.yml" con le dichiarazioni di intenti, azioni, form, slot e responses
def domain_generator(flag_assistenza):

    ### Domain Intents
    domain_intent = "intents:\n- intent_saluti\n- intent_azione\n- intent_entitytype_entity\n- intent_cosa_posso_fare\n- giorno_ora\n- chitchat\n- intent_faq\n"
    if flag_assistenza == "1":
        domain_intent = domain_intent + "- u_operatore\n- aprire_segnalazione\n"


    ### Domain Actions
    domain_actions = """actions:
- action_set_action_type_only_action
- action_retrieve_name_only_action
- action_retrieve_action_only_action
- action_extract_filter
- action_retrieve_types
- action_set_action
- action_retrieve_name
- action_retrieve_faq
- action_exit
- action_custom_fallback
- action_date_time
- action_reset_assertion\n"""
    if flag_assistenza == "1":
        domain_actions = domain_actions + """- action_save_email
- action_operatore
- action_attesa_operatore
- action_insert_email
- action_email_operatore
- action_aprire_segnalazione_email
- action_salva_segnalazione\n"""
    elif flag_assistenza == "2":
        domain_actions = domain_actions + """- action_save_email
- action_insert_email\n"""


    ### Domain Utters
    domain_utter = """responses:\n  utter_problema_risolto:\n  - text: \"Ho risolto il tuo problema?\"\n    buttons:\n    - title: \"sì\"\n      payload: \"sì\"\n    - title: \"no\"\n      payload: \"no\"
  utter_assistenza:\n  - text: \"Mi dispiace ma non posso esserti d'aiuto.  \\nVuoi contattare l'assistenza?\"\n    buttons:\n    - title: \"sì\"\n      payload: \"sì\"\n    - title: \"no\"\n      payload: \"no\"
  utter_aprire_segnalazione_testo:\n  - text: Inserisci il testo relativo alla segnalazione (oppure digita \"esci\" per uscire).
  utter_chitchat:\n  - text: \"Mi dispiace ma questa richiesta non rientra tra le mie capacità.  \\nCome posso aiutarti?\"
  utter_cosa_posso_fare:\n  - text: \"Posso rispondere alle tue domande per aiutarti a risolvere eventuali dubbi e problemi.  \\n  \\nCome posso aiutarti?\"\n\n"""


    ### Domain Forms
    domain_form = """forms:
- type_form
- name_form
- assertion_form
- action_form\n"""
    if flag_assistenza == "1":
        domain_form = domain_form + """- aprire_segnalazione_testo_form
- email_form
- testo_form\n"""
    if flag_assistenza == "2":
        domain_form = domain_form + """- email_form\n"""

    
    ### Domain Slots
    domain_slot = """slots:
  'type_1':
    auto_fill: false
    type: text
    influence_conversation: false
  'name_1':
    auto_fill: false
    type: text
    influence_conversation: false
  'action_1':
    auto_fill: false
    type: text
    influence_conversation: false
  'found_name':
    initial_value: 'false'
    type: categorical
    values:
    - 'true'
    - 'false'
    - __other__
  'assertion':
    type: categorical
    values:
    - 'si'
    - 'no'
    - __other__
  'check_another_faq':
    initial_value: 'no'
    type: categorical
    values:
    - 'si'
    - 'no'
    - __other__
  'filter_string':
    auto_fill: false
    type: text
    influence_conversation: false
  'root':
    auto_fill: false
    type: text
    influence_conversation: false
  'action_only_action':
    auto_fill: false
    type: text
    influence_conversation: false
  'entity_type_only_action':
    auto_fill: false
    type: text
    influence_conversation: false
  'entity_only_action':
    auto_fill: false
    type: text
    influence_conversation: false
  'only_action':
    auto_fill: false
    type: text
    influence_conversation: false
  'query_more_rows':
    auto_fill: false
    type: text
    influence_conversation: false
  'more_rows':
    auto_fill: false
    type: text
    influence_conversation: false
  'check_more_entities':
    auto_fill: false
    type: text
    influence_conversation: false
  'faq_title_finale':
    auto_fill: false
    type: text
    influence_conversation: false
  'email_slot':
    auto_fill: false
    type: text
    influence_conversation: false\n\n"""
    if flag_assistenza == "1":
        domain_slot = domain_slot + """  'email':
    auto_fill: false
    type: text
    influence_conversation: false
  'aprire_segnalazione_testo':
    auto_fill: false
    type: text
    influence_conversation: false
  'testo':
    auto_fill: false
    type: text
    influence_conversation: false\n\n"""
    elif flag_assistenza == "2":
        domain_slot = domain_slot + """  'email':
    auto_fill: false
    type: text
    influence_conversation: false\n\n"""

    return domain_intent, domain_actions, domain_utter, domain_form, domain_slot