"""Local, explainable technical retrieval in EN/RU/HY/FR/ES; no embedding service."""
import math
import re
import unicodedata
from collections import Counter


CONCEPTS = {
    'test': 'test tests testing tested unittest pytest phpunit dusk тест тесты тестов тестирование թեստ թեստեր թեստերը թեստերի փորձարկում essai essais tester pruebas prueba probar pruebas testear',
    'runtime': 'runtime runtimes environment environments окружение окружения среда միջավայր միջավայրը միջավայրում environnement environnements entorno entornos ejecucion',
    'dependency': 'dependency dependencies composer lockfile зависимости зависимостей зависимость կախվածություն կախվածություններ կախվածությունները կախվածությունների dependance dependances dependencia dependencias',
    'deploy': 'deploy deployment release releases rollback развёртывание развертывание деплой релиз տեղակայում տեղակայումը թողարկում deploiement deployer despliegue desplegar lanzamiento',
    'database': 'database databases db postgres postgresql mysql sqlite база базу бд базаданных բազա բազան շտեմարան շտեմարանի շտեմարանների bdd basededonnees basededatos',
    'migration': 'migration migrations migrate migrating миграция миграции миграцию միգրացիա միգրացիան միգրացիաները migracion migraciones migrar',
    'auth': 'auth authentication authorization login permissions аутентификация авторизация вход իրավունքներ մուտք նույնականացում authentification autorisation connexion autenticacion autorizacion acceso permisos',
    'security': 'security secure vulnerability vulnerabilities безопасность уязвимость անվտանգություն անվտանգության securite vulnerabilite seguridad vulnerabilidad',
    'performance': 'performance optimize optimization latency производительность оптимизация արագագործություն կատարողականություն optimisation latence rendimiento optimizacion latencia',
    'debug': 'debug debugging diagnose diagnostic error errors отладка диагностика ошибка ошибки սխալ սխալներ սխալները ախտորոշում debogage diagnostiquer erreur erreurs depuracion diagnostico fallos errores',
    'accessibility': 'accessibility a11y wcag доступность մատչելիություն մատչելիության accessibilite accesibilidad',
    'payment': 'payment payments checkout оплата платеж платежи վճարում վճարումներ վճարումների paiement paiements pago pagos',
    'translation': 'translation translations locale localization перевод локализация թարգմանություն տեղայնացում traduction traductions traduccion traducciones localizacion',
    'search': 'search retrieval seo поиск որոնում որոնման recherche busqueda buscar',
    'cache': 'cache caching кеш кэш кеширование քեշ քեշավորում кеши cache cacher',
    'git': 'git github branch branches ветка ветки ճյուղ ճյուղեր branche branches rama ramas',
}
STOP = set('use when the a an or and in on of to for with before after as is are it this that any '
           'run running check inspect verify execute application applications please hello what time '
           'проверь проверить проверка пожалуйста привет как это и в на для перед после '
           'ստուգիր ստուգել բարեւ բարև ի է և ու համար '
           'le la les un une des du de et dans avant apres avec quand executer verifier verifie bonjour '
           'el los las una uno y en para con antes despues ejecutar revisa revisar verificar hola'.split())
PHRASES = {'base de datos': 'database', 'base de donnees': 'database', 'база данных': 'database',
           'базу данных': 'database', 'բազա տվյալների': 'database', 'տվյալների բազա': 'database',
           'տվյալների բազան': 'database'}


def fold(text):
    text = unicodedata.normalize('NFKC', str(text)).casefold().replace('ё', 'е')
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))


ALIASES = {fold(word): canonical for canonical, words in CONCEPTS.items() for word in words.split()}


def tokens(text):
    text = fold(text)
    for phrase, canonical in sorted(PHRASES.items(), key=lambda item: -len(item[0])):
        text = re.sub(r'(?<!\w)'+re.escape(fold(phrase))+r'(?!\w)', canonical, text)
    result = []
    for word in re.findall(r'[^\W_]+', text, re.UNICODE):
        if word in STOP or len(word) < 2 or word.isdigit():
            continue
        result.append(ALIASES.get(word, word))
    return result


def rank(query, skills, *, limit=5, min_coverage=0.25):
    wanted = set(tokens(query))
    if not wanted:
        return []
    documents = []
    for skill in skills:
        weighted = tokens(skill.get('name', ''))*3 + tokens(skill.get('description', ''))*2
        weighted += tokens(skill.get('category', '')) + tokens(skill.get('body', '')[:8000])
        documents.append((skill, Counter(weighted), len(weighted)))
    if not documents:
        return []
    n = len(documents)
    avg = sum(length for _, _, length in documents)/n or 1
    frequency = {term: sum(term in count for _, count, _ in documents) for term in wanted}
    hits = []
    for skill, count, length in documents:
        matched = sorted(wanted & count.keys())
        coverage = len(matched)/len(wanted)
        if not matched or coverage < min_coverage:
            continue
        score = 0
        for term in matched:
            idf = math.log(1+(n-frequency[term]+0.5)/(frequency[term]+0.5))
            tf = count[term]
            score += idf*tf*2.2/(tf+1.2*(0.25+0.75*length/avg))
        hits.append(skill | {'relevance': round(score*(0.5+coverage), 6), 'matched_terms': matched})
    hits.sort(key=lambda s: (-s['relevance'], s.get('scope', ''), s['name']))
    return hits[:limit] if limit is not None else hits
