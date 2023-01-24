# 5409625015: AAHtbugFc2aCY35DWmbFc0KHuU15pZEsYYQ - токен бота
# -519115532 - chat_id

import telegram
import pandahouse # для доступа в базу
import pandas as pd # для работы с датафреймами
import seaborn as sns # для визуализации
import matplotlib.pyplot as plt # для визуализации
import io # для сохранения изображения в буфере, чтобы не засорять хранилище
import os # библиотека для скрытия приватной информации
import sys # библиотека для скрытия приватной информации

from datetime import datetime, date, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.decorators import dag, task # декораторы
from airflow.operators.python import get_current_context

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
    'start_date': datetime(2022, 7, 14), # дата и время начала выполнения Dag
}

# Интервал запуска DAG
schedule_interval = '*/15 * * * *' # каждые 15 минут

def check_anomaly(df, metric, a=4, n=5):
    # метод shift для сдвига значений на один период назад для защиты от ошибочных алертов
    # метод rolling для скользящего счета по всему интервалу
    df['q25'] = df[metric].shift(1).rolling(n).quantile(0.25) 
    df['q75'] = df[metric].shift(1).rolling(n).quantile(0.75)
    df['iqr'] = df['q75'] - df['q25'] # кладем в датафрейм значение межквартильного размаха
    df['up'] =  df['q75'] + a*df['iqr'] # кладем в датафрейм значение границ
    df['low'] =  df['q25'] - a*df['iqr']

    # Сгладим границы графика аномалий и сделаем, чтобы периоды просчитывались до конца графика
    df['up'] = df['up'].rolling(n, center=True, min_periods=1).mean()
    df['low'] = df['low'].rolling(n, center=True, min_periods=1).mean()

    # определяем условия для значений самой свежей (последней полученной) метрики (пятнадцатиминутки)
    if df[metric].iloc[-1] < df['low'].iloc[-1] or df[metric].iloc[-1] > df['up'].iloc[-1]:
        is_alert = 1
    else:
        is_alert = 0

    return is_alert, df

# Составляем DAG
@dag(default_args=default_args, schedule_interval=schedule_interval, catchup=False)
def dag_ed_vedmich_alerts_system():

    # Формируем task для запуска системы алертов по ленте новостей 
    @task()
    def run_feed(chat=None):
        chat_id = chat or -519115532
        bot = telegram.Bot(token='5409625015:AAHtbugFc2aCY35DWmbFc0KHuU15pZEsYYQ')
        
        # Обозначим список метрик
        metrics_list = ['users_feed', 'views', 'likes', 'ctr']
        
        query = '''SELECT
                            toStartOfFifteenMinutes(time) as ts,
                            toDate(time) as date,
                            formatDateTime(ts, '%R') as hm,
                            uniqExact(user_id) as users_feed,
                            countIf(user_id, action='view') as views,
                            countIf(user_id, action='like') as likes,
                            likes/views as ctr
                        FROM simulator_20220620.feed_actions
                        WHERE time >= today() - 1 and time < toStartOfFifteenMinutes(now())
                        GROUP BY ts, date, hm
                        ORDER BY ts'''
        # округляем время до текущей пятнадцатиминутки, но ее не берем, так как она может быть неполная
        data = pandahouse.read_clickhouse(query=query, connection=connection)
        # затем берем цикл чтобы применить межквартильный размах
        for metric in metrics_list:
            df = data[['ts', 'date', 'hm', metric]].copy()
        # далее к датафрейму применяем алгоритм в функции check_anomaly()
            is_alert, df = check_anomaly(df, metric)

            if is_alert == 1:
                msg = '''Метрика {metric}:\n текущее значение {current_val:.2f}\nотклонение от предыдущего значения {last_val_diff:.2%}\n \
                                                               http://superset.lab.karpov.courses/r/1543'''.format(metric=metric, \
                                                               current_val=df[metric].iloc[-1], last_val_diff=abs(1 - (df[metric].iloc[-1]/df[metric].iloc[-2])))
                sns.set(rc={'figure.figsize': (16, 10)})
                plt.tight_layout()

                ax = sns.lineplot(x=df['ts'], y=df[metric], label='metric')
                ax = sns.lineplot(x=df['ts'], y=df['up'], label='up')
                ax = sns.lineplot(x=df['ts'], y=df['low'], label='low')

                for ind, label in enumerate(ax.get_xticklabels()):
                    if ind % 2 == 0:
                        label.set_visible(True)
                    else:
                        label.set_visible (False)

                ax.set(xlabel='time')
                ax.set(ylabel=metric)

                ax.set_title(metric)
                ax.set(ylim=(0, None))

                plot_object = io.BytesIO()
                ax.figure.savefig(plot_object)
                plot_object.seek(0)
                plot_object.name = '{0}.png'.format(metric)
                plt.close()

                bot.sendMessage(chat_id=chat_id, text=msg)
                bot.sendPhoto(chat_id=chat_id, photo=plot_object)
        return
    
    run_feed()
dag_ed_vedmich_alerts_system = dag_ed_vedmich_alerts_system()
