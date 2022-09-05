# Импортируем библиотеки
from datetime import datetime, timedelta
import telegram as tg
import pandas as pd
import pandahouse as ph
import numpy as np
import seaborn as sns
import requests
import io
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.decorators import dag, task # декоратор для создания дагов и тасков
from airflow.operators.python import get_current_context # оператор airflow для работы с питоном

my_token = '5409625015:AAHtbugFc2aCY35DWmbFc0KHuU15pZEsYYQ' 
chat_id=-714461138 # id чата курса
bot = tg.Bot(token=my_token)

connection = {'host': 'https://clickhouse.lab.karpov.courses',
                      'database':'simulator_20220620',
                      'user':'student', 
                      'password':'dpo_python_2020'
                     }

# Установка дефолтных параметров, которые прокидываются в таски
default_args = {
    'owner': 'ed-vedmich',
    'depends_on_past': False, # зависимость от прошлых запусков
    'retries': 2, # количество попыток запуска Dag в случае ошибки
    'retry_delay': timedelta(minutes=5), # время между повторными запусками
    'start_date': datetime(2022, 7, 12), # дата и время начала выполнения Dag
}

# Интервал запуска DAG
schedule_interval = '0 11 * * *' # 11 часов 

# Составляем DAG
@dag(default_args=default_args, schedule_interval=schedule_interval, catchup=False)
def dag_combined_report():
    
    # Формируем task с запросом для получения данных из feed_actions и message_actions
    @task()
    def message_report(chat=None):
        chat_id = chat or -714461138

        query = ''' SELECT
                        f.day AS day, dau_feed, dau_messenger, avg_number_of_messages, new_f_users, new_m_users
                    FROM (
                        SELECT  count(DISTINCT user_id) AS dau_feed, toDate(time) AS day 
                        FROM    simulator_20220620.feed_actions
                        WHERE   toDate(time) = yesterday()
                        GROUP BY day) f
                    JOIN (
                        SELECT  count(DISTINCT user_id) AS dau_messenger, toDate(time) AS day
                        FROM    simulator_20220620.message_actions
                        WHERE   toDate(time) = yesterday()
                        GROUP BY day) m
                    ON f.day = m.day
                    JOIN (
                        SELECT  toDateTime(time) AS day,
                                AVG(number_of_actions) AS avg_number_of_messages
                        FROM
                          (SELECT user_id,
                                  toDate(time) as time,
                                  count(user_id) as number_of_actions
                           FROM simulator_20220620.message_actions
                           WHERE   toDate(time) = yesterday()
                           GROUP BY user_id, time) AS virtual_table
                        GROUP BY day) a
                    ON f.day = a.day
                    JOIN (
                        SELECT  toStartOfDay(toDateTime(start_date)) AS day,
                               count(DISTINCT user_id) AS new_f_users
                        FROM
                           (SELECT user_id,
                                   min(time) as start_date
                            FROM   simulator_20220620.feed_actions
                            GROUP BY user_id) AS virtual_table
                        WHERE  toDate(start_date) >= yesterday()-7 and toDate(start_date) <= yesterday()
                        GROUP BY toStartOfDay(toDateTime(start_date))
                        ORDER BY day) nf
                    ON f.day = nf.day
                    JOIN (
                        SELECT  toStartOfDay(toDateTime(start_date)) AS day,
                               count(DISTINCT user_id) AS new_m_users
                        FROM
                           (SELECT user_id,
                                   min(time) as start_date
                            FROM   simulator_20220620.message_actions
                            GROUP BY user_id) AS virtual_table
                        WHERE  toDate(start_date) >= yesterday()-7 and toDate(start_date) <= yesterday()
                        GROUP BY toStartOfDay(toDateTime(start_date))
                        ORDER BY day) nm
                    ON f.day = nm.day
                        '''
        data = ph.read_clickhouse(query=query, connection=connection)


        day = (pd.to_datetime('today')-timedelta(days=1)).normalize().strftime("%d.%m.%Y")
        msg = (f'Main news feed and messenger data for {day}:\nDAU_Feed {data.dau_feed.item()}')+\
              (f'\nDAU_Messenger {data.dau_messenger.item()}')+\
              (f'\nAVG_Messages {round(data.avg_number_of_messages.item(),2)}\nNew_Feed_Users {data.new_f_users.item()}')+\
              (f'\nNew_Messenger_Users {data.new_m_users.item()}')  
        bot.sendMessage(chat_id = chat_id, text = msg)
    
    # Формируем task для построения графика DAU по ленте новостей за прошедшую неделю
    @task()
    def dau_feed(chat=None):
        chat_id = chat or -714461138
        bot = tg.Bot(token=my_token)
        q_dau = '''SELECT 
                          count(DISTINCT user_id) AS value, toDate(time) AS date 
                   FROM   simulator_20220620.feed_actions
                   WHERE  toDate(time) >= yesterday()-7 and toDate(time) <= yesterday()
                   GROUP BY date'''
        data = ph.read_clickhouse(query=q_dau, connection=connection)

        g = sns.lineplot(y=data['value'], x=data['date'].dt.strftime('%b-%d'), color='red', label='feed_users')
        plt.title('DAU Feed', size=12)
        plt.grid(False)
        plt.legend()

        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'DAU_Feed.png'
        plt.close()

        bot.sendPhoto(chat_id=chat_id, photo=plot_object)
    
    # Формируем task для построения графика количества привлеченных пользователей по ленте новостей за прошедшую неделю
    @task()
    def new_feed_users(chat=None):
        chat_id = chat or -714461138
        bot = tg.Bot(token=my_token)
        q_nfusers = '''SELECT  toStartOfDay(toDateTime(start_date)) AS date,
                           count(DISTINCT user_id) AS value
                       FROM
                          (SELECT user_id,
                                  min(time) as start_date
                           FROM   simulator_20220620.feed_actions
                           GROUP BY user_id) AS virtual_table
                       WHERE  toDate(start_date) >= yesterday()-7 and toDate(start_date) <= yesterday() 
                       GROUP BY toStartOfDay(toDateTime(start_date))
                       ORDER BY date'''
        data = ph.read_clickhouse(query=q_nfusers, connection=connection)

        g = sns.lineplot(y=data['value'], x=data['date'].dt.strftime('%b-%d'), color='red', label='users')
        plt.title('New feed users', size=12)
        plt.grid(False)
        plt.legend()

        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'New_feed_users.png'
        plt.close()

        bot.sendPhoto(chat_id=chat_id, photo=plot_object)
        
    # Формируем task для построения графика DAU по мессенджеру за прошедшую неделю
    @task()
    def dau_messenger(chat=None):
        chat_id = chat or -714461138
        bot = tg.Bot(token=my_token)
        q_dau = '''SELECT 
                          count(DISTINCT user_id) AS value, toDate(time) AS date 
                   FROM   simulator_20220620.message_actions
                   WHERE  toDate(time) >= yesterday()-7 and toDate(time) <= yesterday()
                   GROUP BY date'''
        data = ph.read_clickhouse(query=q_dau, connection=connection)

        g = sns.lineplot(y=data['value'], x=data['date'].dt.strftime('%b-%d'), color='blue', label='messenger_users')
        plt.title('DAU Messenger', size=12)
        plt.grid(False)
        plt.legend()

        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'DAU_Messenger.png'
        plt.close()

        bot.sendPhoto(chat_id=chat_id, photo=plot_object)
    
    # Формируем task для построения графика количества привлеченных пользователей по мессенджеру за прошедшую неделю
    @task()
    def new_messenger_users(chat=None):
        chat_id = chat or -714461138
        bot = tg.Bot(token=my_token)
        q_nmusers = '''SELECT  toStartOfDay(toDateTime(start_date)) AS date,
                           count(DISTINCT user_id) AS value
                       FROM
                          (SELECT user_id,
                                  min(time) as start_date
                           FROM   simulator_20220620.message_actions
                           GROUP BY user_id) AS virtual_table
                       WHERE  toDate(start_date) >= yesterday()-7 and toDate(start_date) <= yesterday() 
                       GROUP BY toStartOfDay(toDateTime(start_date))
                       ORDER BY date'''
        data = ph.read_clickhouse(query=q_nmusers, connection=connection)

        g = sns.lineplot(y=data['value'], x=data['date'].dt.strftime('%b-%d'), color='blue', label='users')
        plt.title('New messenger users', size=12)
        plt.grid(False)
        plt.legend()

        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'New_messenger_users.png'
        plt.close()

        bot.sendPhoto(chat_id=chat_id, photo=plot_object)
    
    # Формируем task для построения графика среднего числа сообщений на пользователя по мессенджеру за прошедшую неделю
    @task()
    def avg_messages(chat=None):
        chat_id = chat or -714461138
        bot = tg.Bot(token=my_token)
        q_avg = '''SELECT toDateTime(time) AS date,
                          AVG(number_of_actions) AS value
                   FROM
                      (SELECT user_id,
                              toDate(time) as time,
                              count(user_id) as number_of_actions
                       FROM   simulator_20220620.message_actions
                       WHERE  toDate(time) >= yesterday()-7 and toDate(time) <= yesterday()
                       GROUP BY user_id, time) AS virtual_table
                   GROUP BY date
                   ORDER BY date'''
        data = ph.read_clickhouse(query=q_avg, connection=connection)

        g = sns.lineplot(y=data['value'], x=data['date'].dt.strftime('%b-%d'), color='blue', label='messages')
        plt.title('AVG Number of Messages', size=12)
        plt.grid(False)
        plt.legend()

        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'AVG_Messages.png'
        plt.close()

        bot.sendPhoto(chat_id=chat_id, photo=plot_object)

    message_report()
    dau_feed()
    new_feed_users()
    dau_messenger()
    new_messenger_users()
    avg_messages()

dag_combined_report = dag_combined_report()