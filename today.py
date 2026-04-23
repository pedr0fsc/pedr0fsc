import datetime
import os
import requests
from lxml import etree
from dateutil import relativedelta

# Configurações
USER_NAME = "pedr0fsc"
HEADERS = {'authorization': f"token {os.getenv('ACCESS_TOKEN', '')}"}

def get_uptime(birthday):
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return f"{diff.years} years, {diff.months} months, {diff.days} days"

def get_github_stats():
    query = '''
    query($login: String!) {
        user(login: $login) {
            repositories(first: 100, ownerAffiliations: OWNER) { totalCount }
            followers { totalCount }
        }
    }'''
    try:
        response = requests.post('https://api.github.com/graphql', 
                                 json={'query': query, 'variables': {'login': USER_NAME}}, 
                                 headers=HEADERS)
        res_data = response.json()
        return {
            'repos': res_data['data']['user']['repositories']['totalCount'],
            'followers': res_data['data']['user']['followers']['totalCount']
        }
    except:
        return {'repos': 0, 'followers': 0}

def get_config_txt():
    conf = {}
    if os.path.exists('config.txt'):
        with open('config.txt', 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    k, v = line.split(':', 1)
                    conf[k.strip().lower()] = v.strip()
    return conf

def justify_svg(root, element_id, text, max_len=30):
    # Atualiza o texto do valor
    val_el = root.find(f".//*[@id='{element_id}']")
    if val_el is not None: 
        val_el.text = str(text)
    
    # Busca o ID dos pontos (Removido o '_val' extra para bater com seu SVG)
    dots_id = element_id.replace('_val', '') + "_dots"
    dots_el = root.find(f".//*[@id='{dots_id}']")
    
    if dots_el is not None:
        num_dots = max(1, max_len - len(str(text)))
        dots_el.text = " " + ("." * num_dots) + " "

def process_svg(filename):
    if not os.path.exists(filename): return
    tree = etree.parse(filename)
    root = tree.getroot()
    
    config = get_config_txt()
    stats = get_github_stats()
    uptime = get_uptime(datetime.datetime(2007, 12, 27))

    # Injeção de Dados do TXT (As chaves no config.txt devem ser minusculas aqui)
    justify_svg(root, 'os_val', config.get('os', 'Windows 11, Ubuntu'))
    justify_svg(root, 'host_val', config.get('host', 'Student'))
    justify_svg(root, 'lang_prog_val', config.get('languages_prog', 'Python, Java, C++'))
    justify_svg(root, 'email_val', config.get('email', ''))

    # Injeção de Dados Automáticos
    justify_svg(root, 'age_data', uptime, max_len=25)
    justify_svg(root, 'repo_data', stats['repos'])
    justify_svg(root, 'commit_data', 'Calculando...') # Se quiser commits reais, precisa de outra query

    tree.write(filename, encoding='utf-8', xml_declaration=True)

if __name__ == "__main__":
    process_svg('dark_mode.svg')
    process_svg('light_mode.svg')
    print("SVG atualizado com sucesso!")