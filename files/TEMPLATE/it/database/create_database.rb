=begin
/*************************************
* SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
* SPDX-License-Identifier: AGPL-3.0-only 
************************************/
=end

require 'sequel'

# Creazione tabelle
# per mysql usare .connect

database_origin = File.open("../db_connections/DB_CONNECTIONS.json", "r").read.to_s[1..-2]
nome_database = database_origin.split("database:\"")[1].split("\"")[0]
database_origin = database_origin.gsub(/database:\s*"[\w\s]*", /, '')
db = eval("Sequel.connect(adapter:\"mysql2\", " + database_origin + ")")

begin
    db.execute "DROP DATABASE IF EXISTS " + nome_database
rescue
    db.execute "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '" + nome_database + "';"
    db.execute "DROP DATABASE IF EXISTS " + nome_database
end

db.execute "CREATE DATABASE " + nome_database
db.disconnect

connessione = "adapter: 'mysql2', " + File.open("../db_connections/DB_CONNECTIONS.json", "r").read.to_s[1..-2]
db = eval("Sequel.connect(" + connessione + ")")


db.create_table! :faq_questions do
    primary_key :id
    String :frase
    String :faq_title
    Text :entities
    Text :entities_lemma
    Integer :parent_id
    String :linea
end

db.create_table! :faq_answers do
    primary_key :id
    String :frase
    String :faq_title
    Integer :parent_id
end

db.create_table! :rasa_faq_models do
    primary_key :id
    String :name
    Timestamp :vt, null: false
    String :train_complete, size: 5
    String :spacy_train_complete, size: 5
    String :status, size: 30
    String :inizio_train, size: 30
    String :fine_train, size: 30
end

db.create_table! :spacy_sentences do
    primary_key :id
    String :frase
    Text :entities
end

db.create_table! :synonyms do
    primary_key :id
    Text :words
end

db.create_table! :fallback_events do
    primary_key :id
    Text :last_message
    String :last_timestamp, size: 30
    Text :events
    String :sender_id, size: 50
end

db.create_table! :conversations do
    primary_key :id
    Text :messages
    String :last_timestamp, size: 30
    Text :events
    String :result, size: 2
    String :sender_id, size: 50
end

db.create_table! :rasa_assistenza do
    primary_key :id
    Text :messages
    String :last_timestamp, size: 30
    Text :events
    String :email
    String :sender_id, size: 50
end

db.create_table! :segnalazioni do
    primary_key :id
    String :email
    Timestamp :timestamp, null: false
    Text :segnalazione
    String :sender_id, size: 50
end

db.create_table! :entities do
    primary_key :id
    String :entity
    String :entity_type
end

db.disconnect