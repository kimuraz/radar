from django.test import TestCase
from exportadores import exportador_csv_r
from modelagem.models import CasaLegislativa
from modelagem.models import Votacao
import os.path
import csv


class ExportacaoRClass(TestCase):

    @classmethod
    def setUpTestData(cls):
        exportador_csv_r.main()

    # @classmethod
    # def tearDownClass(cls):
    # from util_test import flush_db
    # flush_db(cls)

    def test_exportar_cvs_r(self):
        CAMINHO = "./exportadores/saida/votes.csv"
        colunas_csv = []
        existe = False
        existe = os.path.isfile(CAMINHO)
        colunas = ["rollcall", "voter_id", "name", "party", "coalition",
                                                            "vote"]
        with open(CAMINHO, 'r') as arquivo:
            readers = csv.reader(arquivo, delimiter=',')
            for row in readers:
                colunas_csv = row
        self.assertEqual(True, existe)
        self.assertEqual(colunas_csv, colunas)
