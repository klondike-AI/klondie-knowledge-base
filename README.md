# Introduction
**`Klondie`** is a **chatbot** able to **process natural language** and therefore to interact directly with users. It answers questions by linking them to already known FAQs, asking the user for additional information if the question is incomplete of some information.

# ⚙️ Setup the environment
### ▶️ STEP 1:
**Download** the latest release of ***Klondie*** from this project page.
Unzip the zip file to a folder on your hard drive. This will create a folder containing the files and directories.

### ▶️ STEP 2:
Install ***Docker*** and run the following commands to generate the **environment** in which the chatbot will run:
- `sudo docker-compose build`
- `sudo docker-compose up`
- `sudo docker run --name chatbot_redis --network=chatbot_default -p <port>:6379 -v /chatbot/redis_data:/data redis:6.0.8-alpine redis-server --databases 999 --appendonly yes`
- execute the queries in `db/init/01-databases.sql` inside the *mysql* container (it is recommended to change user and password)

### ▶️ STEP 3:
Run the file related to the language of interest among those present in `standard_spacy_models/` to download the related ***spaCy* model** that the chatbot will use as an initial knowledge base. Then run `update_response_time_socketio.sh` to update some ***Rasa* settings**.

# 🤖 Configure your Chatbot
### ▶️ STEP 1:
To generate a **new chatbot** it is necessary to create a **copy** of the ***TEMPLATE/*** directory in `files/` and rename it with the name of your chatbot: this directory will contain all the files necessary for the train and execution of the bot.
Enter the coordinates of the databases to be used in the files in `<folder_name>/db_connections/`:
- `DB_CONNECTIONS_TABLES.json`: specify the database that will contain the tables of questions and answers relating to the FAQs;
- `DB_CONNECTIONS.json`: specify the database for chatbot operations;
- `DB_CONNECTIONS_LAST_INTERACTION.json`: specify the database containing the table for the collection of the timestamps about the last interaction by the user with the chatbot (you have to specify also the table, the field containing the name of the chatbot directory and the field containing the timestamp about the last interaction).

Finally generate the main database by running `create_database.rb` in `<folder_name>/database/` inside the *notebooks* container. Insert the following informations in the relative tables: questions, answers, entities and synonyms.

### ▶️ STEP 2:
After accessing the *notebooks* container, you can train the chatbot by running the `retrain.py` file in `<folder_name>/chatbot_builder/rasa-assistant/` specifying the first available index of the *rasa_faq_models* table as the first parameter and $$0$$ as the second parameter. For example:
- `python3 retrain.py 1 0`

Finally start the chatbot by running the following two commands (inside the *notebooks* container):
- `rasa run --cors "\*" -p <port1>`
- `rasa run actions -p <port2>`

where ***<port1>*** and ***<port2>*** correspond to the ports reserved for your chatbot. *<port2>* must also be specified in the `endopoints.yml` file in the directory `<folder_name>/customer_chatbot/rasa-assistant/`.
It is important that the ports chosen are within the (editable) range specified in the `docker-compose.yml` file, under the *ports* section of the *notebooks* container.

### ▶️ STEP 3:
Now you can text with your chatbot using the `webchat_customer.html` in `<folder_name>/webchat/`, setting correctly ***ip*** and ***<port1>***. By modifying this file you can customize texts, colors and avatars.
By modifying the `index.min.js` file you can completely customize the **graphic appearance** of the widget.
It is important that the **HTML** file and the **Javascript** file are in the **same directory** to ensure the chatbot works correctly.