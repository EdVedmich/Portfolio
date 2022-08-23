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
bot = tg.Bot(token=my_token)
chat_id=-714461138 # id чата курса

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
schedule_interval = '0 11 * * *' # 11 часов утра

# Составляем DAG
@dag(default_args=default_args, schedule_interval=schedule_interval, catchup=False)
def dag_ed_vedmich_report():
    
    # Формируем task с запросом для получения данных из feed_actions
    @task()
    def message_report(chat=None):
        chat_id = chat or -714461138
        
        query = '''SELECT 
                        count(DISTINCT user_id) as dau,
                        countIf(user_id, action = 'like') as likes,
                        countIf(user_id, action = 'view') as views,
                        likes/views as ctr
                   FROM simulator_20220620.feed_actions
                   WHERE toDate(time) = yesterday()
                '''
        data = ph.read_clickhouse(query=query, connection=connection)
    
        day = (pd.to_datetime('today')-timedelta(days=1)).normalize().strftime("%d.%m.%Y")
        msg = (f'Main news feed data for {day}:\nDAU {data.dau.item()}\nviews {data.views.item()}')+\
              (f'\nlikes {data.likes.item()}\nCTR {round(data.ctr.item(),2)}')
        bot.sendMessage(chat_id = chat_id, text = msg)
    
    @task()
    def plot_report(chat=None):
        chat_id = chat or -714461138
        
        query = '''SELECT 
                        toDate(time) as day,
                        count(DISTINCT user_id) as dau,
                        countIf(user_id, action = 'like') as likes,
                        countIf(user_id, action = 'view') as views,
                        likes/views as ctr
                    FROM simulator_20220620.feed_actions
                    WHERE toDate(time) >= yesterday()-6 and toDate(time) <= yesterday()
                    GROUP BY day
                '''
        data = ph.read_clickhouse(query=query, connection=connection)

        for metrics in data.columns[1:]:
            sns.lineplot(x = data.day, y = data[metrics])
            plt.title(f'{metrics} for {(pd.to_datetime("today")-timedelta(days=1)).strftime("%d.%m.%Y")}')
            myFmt = mdates.DateFormatter('%d.%m')
            plt.gca().xaxis.set_major_formatter(myFmt)

            plot_object = io.BytesIO() 
            plt.savefig(plot_object)
            plot_object.name = 'plot.png'
            plot_object.seek(0) 
            plt.close() 
            bot.sendPhoto(chat_id = chat_id, photo=plot_object)

    message_report()
    plot_report()
     
dag_ed_vedmich_report=dag_ed_vedmich_report()





        



