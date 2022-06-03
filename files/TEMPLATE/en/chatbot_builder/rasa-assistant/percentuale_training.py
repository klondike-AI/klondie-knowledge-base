"""
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
"""

import time
import MySQLdb
import sys

# Connessioni
file = open("../../db_connections/DB_CONNECTIONS.json", "r")
dati_connessione = str(file.read().replace(':', '=').replace('username', 'user').replace('password=', 'passwd=').replace('database', 'db')[1:-1])
conn = eval("MySQLdb.connect(" + dati_connessione + ")")
file.close()
cursor = conn.cursor()

model_index = sys.argv[1]

while True:
    f = open("../../customer_chatbot/rasa-assistant/train_output.txt", "r")
    all_file = f.read()
    f.close()

    # Allenamento Core dopo NLU
    if 'Training Core model...' in all_file:
        core_training_file = all_file.split('Training Core model...')[1]
        epochs = core_training_file.rfind("Epochs:")
        if epochs != -1:
            percentuale = core_training_file[epochs:].split(":")[1].split("%")[0].strip()
            percentuale = (int(percentuale) / 2) + 50
            cursor.execute("UPDATE rasa_faq_models SET status = \"Training: " + str(percentuale) + "%\" WHERE id = " + str(model_index))
            conn.commit()
            if 'Epochs: 100%' in core_training_file:
                cursor.execute("UPDATE rasa_faq_models SET status = \"Model generation\" WHERE id = " + str(model_index))
                conn.commit()
                break
    # Se non sta allenando il Core: 1- sta allenando NLU; 2- sta ancora generando le triple
    else:
        # Allenamento NLU
        if 'Epochs:' in all_file:
            epochs = all_file.rfind("Epochs:")
            percentuale = all_file[epochs:].split(":")[1].split("%")[0].strip()
            percentuale = int(percentuale) / 2
            cursor.execute("UPDATE rasa_faq_models SET status = \"Training: " + str(percentuale) + "%\" WHERE id = " + str(model_index))
            conn.commit()
        # Generazione triple
        else:
            cursor.execute("UPDATE rasa_faq_models SET status = \"Input processing\" WHERE id = " + str(model_index))
            conn.commit()

    # se il modello rasa non è cambiato e quindi aggiorna solo il modello spaCy
    if 'Nothing changed. You can use the old model' in all_file:
        cursor.execute("UPDATE rasa_faq_models SET status = \"Generating the model\" WHERE id = " + str(model_index))
        conn.commit()
        break

    # attende 20sec prima del prossimo giro
    time.sleep(20)

conn.close()
