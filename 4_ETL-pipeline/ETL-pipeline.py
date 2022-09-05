# Импортируем библиотеки
from datetime import datetime, timedelta
import pandas as pd
import pandahouse as ph
from io import StringIO
import requests

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.decorators import dag, task # декоратор для создания дагов и тасков
from airflow.operators.python import get_current_context # оператор airflow для работы с питоном 

# Функция для подключения к базе данных ClickHouse
def ch_get_df(query='Select 1', host='https://clickhouse.lab.karpov.courses', user='student', password='dpo_python_2020'):
    connection = {
    'host': host,
    'password': password,
    'user': user,
    'database': 'simulator_20220620'
}
    
    df = ph.read_clickhouse(query, connection=connection)
    return df

# Задаем параметры для подключения к итоговой таблице test в Clickhouse
connection_test = {'host': 'https://clickhouse.lab.karpov.courses',
                      'database':'test',
                      'user':'student-rw', 
                      'password':'656e2b0c9c'
                     }

# Установка дефолтных параметров, которые прокидываются в таски
default_args = {
    'owner': 'ed-vedmich',
    'depends_on_past': False, # зависимость от прошлых запусков
    'retries': 2, # количество попыток запуска Dag в случае ошибки
    'retry_delay': timedelta(minutes=5), # время между повторными запусками
    'start_date': datetime(2022, 7, 10), # дата и время начала выполнения Dag
}

# Интервал запуска DAG
schedule_interval = '0 10 * * *'

# Составляем DAG
@dag(default_args=default_args, schedule_interval=schedule_interval, catchup=False)
def dag_vedmich_etl():
    
    # Формируем task с запросом для получения данных из feed_actions
    @task()
    def extract_feed():
        query = """ SELECT 
                       toDate(time) AS event_date, user_id, 
                       multiIf(gender=='1', 'male', 'female') as gender, 
                       multiIf(age < 18, '0 - 17', age >= 18 and age < 30, '18-29', age >= 30 and 
                               age < 46, '30-45', age >= 46 and age < 60, '46-59', '60+') as age_categories, 
                       os, 
                       countIf(user_id, action = 'view') as views, 
                       countIf(user_id, action = 'like') as likes
                    FROM {db}.feed_actions
                    WHERE toDate(time) = yesterday()
                    GROUP BY event_date, user_id, gender, age_categories, os """
        
        df_feed = ch_get_df(query=query)
        return df_feed

    # Формируем task с запросом для получения данных из message_actions
    @task()
    def extract_message():
        query = """ SELECT event_date, user_id, gender, age_categories, os, 
                          users_sent, messages_sent, users_received, messages_received
                    FROM (
                        SELECT  toDate(time) as event_date, user_id, 
                                multiIf(gender=='1', 'male', 'female') as gender, 
                                multiIf(age < 18, '0 - 17', age >= 18 and age < 30, '18-29', age >= 30 and 
                                        age < 46, '30-45', age >= 46 and age < 60, '46-59', '60+') as age_categories, 
                                os,
                                count(distinct reciever_id) as users_sent, count(*) as messages_sent
                        FROM simulator_20220620.message_actions
                        WHERE toDate(time) = yesterday()
                        GROUP BY event_date, user_id, gender, age_categories, os) t1
                        JOIN (
                        SELECT  toDate(time) as event_date, reciever_id as user_id, 
                                multiIf(gender=='1', 'male', 'female') as gender, 
                                multiIf(age < 18, '0 - 17', age >= 18 and age < 30, '18-29', age >= 30 and 
                                        age < 46, '30-45', age >= 46 and age < 60, '46-59', '60+') as age_categories, 
                                os,
                                count(distinct(user_id)) as users_received, count(*) as messages_received
                        FROM simulator_20220620.message_actions
                        WHERE toDate(time) = yesterday()
                        GROUP BY event_date, user_id, gender, age_categories, os) t2
                        ON t1.user_id = t2.user_id """
    
        df_message = ch_get_df(query=query)
        return df_message
    
    # Объединяем получившиеся выгруженные ранее таблицы в одну
    @task()
    def transform_combined(df_feed, df_message):
        df_combined = df_feed.merge(df_message, on = ['event_date', 'user_id', 'gender', 'age_categories', 'os'], how = 'outer')
        return df_combined

    # Считаем метрики по полу
    @task()
    def transfrom_gender(df_combined):
        df_combined_gender = df_combined.copy()
        df_combined_gender['metrics'] = 'gender'
        df_combined_gender = df_combined_gender[['event_date', 'metrics', 'gender', 'likes','views',\
                                          'users_sent', 'messages_sent', 'users_received', 'messages_received']]\
            .groupby(['event_date', 'metrics', 'gender'])\
            .sum()\
            .reset_index()\
            .rename(columns = {'gender':'submetrics'})    
        return df_combined_gender
        
    # Считаем метрики по возрасту
    @task()
    def transfrom_age(df_combined):
        df_combined_age = df_combined.copy()
        df_combined_age['metrics'] = 'age'
        df_combined_age = df_combined_age[['event_date', 'metrics', 'age_categories', 'likes','views',\
                                       'users_sent', 'messages_sent', 'users_received', 'messages_received']]\
            .groupby(['event_date', 'metrics', 'age_categories'])\
            .sum()\
            .reset_index()\
            .rename(columns = {'age_categories':'submetrics'})
        return df_combined_age

    # Считаем метрики по операционной системе
    @task()
    def transfrom_os(df_combined): 
        df_combined_os = df_combined.copy()
        df_combined_os['metrics'] = 'os'
        df_combined_os = df_combined_os[['event_date', 'metrics', 'os', 'likes','views',\
                                      'users_sent', 'messages_sent', 'users_received', 'messages_received']]\
            .groupby(['event_date', 'metrics', 'os'])\
            .sum()\
            .reset_index()\
            .rename(columns = {'os':'submetrics'})
        return df_combined_os
    
    # Объединяем полученные данные по метрикам в одну таблицу
    @task
    def transform_final(df_combined_gender, df_combined_age, df_combined_os):
        df_final = pd.concat([df_combined_gender, df_combined_age, df_combined_os]).reset_index(drop=True)
        return df_final
    
    # Записываем финальные данные со всеми метриками записываем в отдельную таблицу в ClickHouse.
    @task
    def load(df_final):
        df_final['event_date'] = pd.to_datetime(df_final['event_date'])
        df_final = df_final.astype({'metrics':'object', 'submetrics':'object', 'likes': int, \
                                    'views': int, 'users_sent':int, \
                                    'messages_sent': int, 'users_received': int, 'messages_received':int})
        ph.to_clickhouse(df_final, 'ed_vedmich_etl_v2', index=False, connection=connection_test)
        
    df_feed = extract_feed()
    df_message = extract_message()
    
    df_combined = transform_combined(df_feed, df_message)
    
    df_combined_gender = transfrom_gender(df_combined)
    df_combined_age = transfrom_age(df_combined)
    df_combined_os = transfrom_os(df_combined)
    
    df_final = transform_final(df_combined_gender, df_combined_age, df_combined_os)
    
    load(df_final)
    
dag_vedmich_etl = dag_vedmich_etl()
