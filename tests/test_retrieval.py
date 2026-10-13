import unittest

from autoharness_codex.retrieval import rank, tokens


SKILLS = [
    dict(name='laravel-runtime-testing', description='Use when running Laravel tests in Docker or Homestead.', category='testing'),
    dict(name='database-migrations', description='Use when updating database schema or migrating PostgreSQL.', category='database'),
    dict(name='release-deployment', description='Use when deploying releases and rolling back production.', category='deployment'),
]


class RetrievalTests(unittest.TestCase):
    def test_five_languages_find_the_same_technical_skill(self):
        for query in ['run Laravel tests', 'проверь тесты Laravel', 'ստուգիր Laravel-ի թեստերը',
                      'exécuter les tests Laravel', 'ejecutar las pruebas de Laravel']:
            with self.subTest(query=query):
                hits = rank(query, SKILLS)
                self.assertTrue(hits)
                self.assertEqual(hits[0]['name'], 'laravel-runtime-testing')

    def test_irrelevant_or_generic_queries_return_no_arbitrary_recommendations(self):
        for query in ['hello', 'привет', 'բարեւ', 'bonjour', 'hola', 'проверь', '', 'what time is it']:
            with self.subTest(query=query):
                self.assertEqual(rank(query, SKILLS), [])

    def test_accents_inflections_and_hyphenated_identifiers(self):
        self.assertIn('deploy', tokens('déploiement despliegue развёртывание տեղակայում'))
        self.assertEqual(rank('migración de base de datos', SKILLS)[0]['name'], 'database-migrations')
        self.assertEqual(rank('migration de base de données', SKILLS)[0]['name'], 'database-migrations')
        self.assertIn('test', tokens('Laravel-ի թեստերը tests тестирование pruebas'))

    def test_specific_matches_outrank_generic_category_and_ties_are_stable(self):
        candidates = SKILLS + [dict(name='generic-tests',description='Use when testing any application.',category='testing')]
        result = rank('Laravel Docker tests', candidates)
        self.assertEqual(result[0]['name'], 'laravel-runtime-testing')
        self.assertGreater(result[0]['relevance'], result[-1]['relevance'])
        self.assertEqual(rank('Laravel Docker tests', list(reversed(candidates))), result)
