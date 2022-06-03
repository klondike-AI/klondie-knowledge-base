# create databases
CREATE DATABASE IF NOT EXISTS `db`;

# create root user and grant rights
CREATE USER 'user'@'localhost' IDENTIFIED BY 'password';
GRANT ALL ON *.* TO 'user'@'%';