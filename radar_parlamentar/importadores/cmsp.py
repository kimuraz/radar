# Copyright (C) 2012, Leonardo Leite, Guilherme Januário, Diego Rabatone
#
# This file is part of Radar Parlamentar.
#
# Radar Parlamentar is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Radar Parlamentar is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Radar Parlamentar.  If not, see <http://www.gnu.org/licenses/>.

"""módulo cmsp (Câmara Municipal de São Paulo)"""


from django.utils.dateparse import parse_datetime
from modelagem import models
from requests.exceptions import RequestException
from .chefes_executivos import ImportadorChefesExecutivos
import re
import sys
import os
import xml.etree.ElementTree as etree
import logging
import requests

logger = logging.getLogger("radar")
MODULE_DIR = os.path.abspath(os.path.dirname(__file__))

XML_FILE = 'dados/chefe_executivo/chefe_executivo_cmsp.xml'
NOME_CURTO = 'cmsp'

# arquivos com os dados fornecidos pela cmsp
XML_URL = 'https://splegispdarmazenamento.blob.core.windows.net/containersip/VOTACOES_%d.xml'
ANOS_DISPONIVEIS = [2012, 2013, 2014, 2015, 2016, 2017]

# tipos de proposições encontradas nos XMLs da cmsp
# esta lista ajuda a identificar as votações que são de proposições
# Exemplos de votações que não são de proposições: Adiamento do Prolong.
# do Expediente; Adiamento dos Demais itens da Pauta.
TIPOS_PROPOSICOES = ['PL', 'PLO', 'PDL']

# regex que captura um nome de proposição (ex: PL 12/2010)
PROP_REGEX = '([a-zA-Z]{1,3}) ([0-9]{1,4}) ?/([0-9]{4})'

INICIO_PERIODO = parse_datetime('2010-01-01 0:0:0')
FIM_PERIODO = parse_datetime('2012-12-31 0:0:0')


class GeradorCasaLegislativa(object):

    def gerar_cmsp(self):
        try:
            cmsp = models.CasaLegislativa.objects.get(nome_curto=NOME_CURTO)
        except models.CasaLegislativa.DoesNotExist:
            cmsp = self.salvar_cmsp()
        return cmsp

    def salvar_cmsp(self):
        cmsp = models.CasaLegislativa()
        cmsp.nome = 'Câmara Municipal de São Paulo'
        cmsp.nome_curto = 'cmsp'
        cmsp.esfera = models.MUNICIPAL
        cmsp.local = 'São Paulo - SP'
        cmsp.save()
        return cmsp


class XmlCMSP:

    def __init__(self, cmsp, verbose=False):
        self.cmsp = cmsp
        self.parlamentares = self._init_parlamentares()
        self.verbose = verbose

    def _init_parlamentares(self):
        """retorna dicionário (nome_parlamentar, nome_partido) ->\
        Parlamentar"""
        parlamentares = {}
        for p in models.Parlamentar.objects.filter(casa_legislativa=self.cmsp):
            parlamentares[self._key(p)] = p
        return parlamentares

    def _key(self, parlamentar):
        return (parlamentar.nome, parlamentar.partido.nome)

    def converte_data(self, data_str):
        """Converte string "d/m/a para objeto datetime;
        retona None se data_str é inválido"""
        DATA_REGEX = '(\d\d?)/(\d\d?)/(\d{4})'
        res = re.match(DATA_REGEX, data_str)
        if res:
            new_str = '%s-%s-%s 0:0:0' % (
                res.group(3), res.group(2), res.group(1))
            return parse_datetime(new_str)
        else:
            return None

    def prop_nome(self, texto):
        """Procura "tipo num/ano" no texto"""
        res = re.search(PROP_REGEX, texto)
        if res:
            nome = res.group(1).upper()
            if self.votacao_valida(nome, texto):
                return res.group(1).upper()+" "+res.group(2).upper()+"/"+res.group(3).upper()
        return None

    def votacao_valida(self, nome_prop, texto):
        return nome_prop in TIPOS_PROPOSICOES and 'Inversão' not in texto

    def tipo_num_anoDePropNome(self, prop_nome):
        """Extrai ano de "tipo num/ano" """
        res = re.search(PROP_REGEX, prop_nome)
        if res:
            return res.group(1), res.group(2), res.group(3)
        else:
            return None, None, None

    def voto_cmsp_to_model(self, voto):
        """Interpreta voto como tá no XML e responde em adequação a
        modelagem em models.py"""

        if voto == 'Não':
            return models.NAO
        elif voto == 'Sim':
            return models.SIM
        elif voto == 'Não votou':
            return models.AUSENTE
        elif voto == 'Abstenção':
            return models.ABSTENCAO
        else:
            logger.info('tipo de voto (%s) nao mapeado!' % voto)
            return models.ABSTENCAO

    def partido(self, ver_tree):
        nome_partido = ver_tree.get('Partido').strip()
        partido = models.Partido.from_nome(nome_partido)
        if partido is None:
            logger.info('Nao achou o partido %s' % nome_partido)
            partido = models.Partido.get_sem_partido()
        return partido

    def vereador(self, ver_tree):
        nome_vereador = ver_tree.get('Nome')
        partido = self.partido(ver_tree)
        key = (nome_vereador, partido.nome)
        if key in self.parlamentares:
            vereador = self.parlamentares[key]
        else:
            id_parlamentar = ver_tree.get('IDParlamentar')
            vereador = models.Parlamentar()
            vereador.id_parlamentar = id_parlamentar
            vereador.nome = nome_vereador
            vereador.partido = partido
            vereador.casa_legislativa = self.cmsp
            vereador.save()
            if self.verbose:
                logger.info('Vereador %s salvo' % vereador)
            self.parlamentares[key] = vereador
        return vereador

    def votos_from_tree(self, vot_tree, votacao):
        """Extrai lista de votos do XML da votação e as salva no banco de dados

        Argumentos:
           vot_tree -- etree dos votos
           votacao -- objeto do tipo Votacao
        """
        for ver_tree in vot_tree.getchildren():
            if ver_tree.tag == 'Vereador':
                vereador = self.vereador(ver_tree)
                voto = models.Voto()
                voto.parlamentar = vereador
                voto.votacao = votacao
                voto.opcao = self.voto_cmsp_to_model(ver_tree.get('Voto'))
                if voto.opcao is not None and self.nao_eh_repetido(voto):
                    voto.save()

    def nao_eh_repetido(self, voto):
        """# Obs: se nos dados aparece que o mesmo parlamentar
        #fez opções distintas na mesma votação,
        # prevalece o primeiro registro."""
        votos_iguais = models.Voto.objects.filter(votacao=voto.votacao,
                                                  parlamentar=voto.parlamentar)
        return len(votos_iguais) == 0

    def votacao_from_tree(self, proposicoes, votacoes, vot_tree):
        # se é votação nominal
        votacao_TipoVotacao = vot_tree.get('TipoVotacao')
        if vot_tree.tag == 'Votacao' and votacao_TipoVotacao == 'Nominal':
            # Prop_nome eh como se identifica internamente as propostas.
            # Queremos saber a que proposicao estah associada a votacao
            # analisanda.
            # vai retornar prop_nome se votação for de proposição
            prop_nome = self.prop_nome(vot_tree.get('Materia'))
            self.find_voting(proposicoes, votacoes, vot_tree, prop_nome)
            # se a votacao for associavel a uma proposicao, entao..

    def find_voting(self, proposicoes, votacoes, vot_tree, prop_nome):
        if prop_nome:
            id_vot = vot_tree.get('VotacaoID')
            votacoes_em_banco = models.Votacao.objects.filter(
                proposicao__casa_legislativa__nome_curto='cmsp', id_vot=id_vot)
            if votacoes_em_banco:
                vot = votacoes_em_banco[0]
                votacoes.append(vot)
            else:
                # a proposicao a qual a votacao sob analise se refere jah
                # estava no dicionario (eba!)
                self.guarantee_existence_of_proposition(
                    proposicoes, votacoes, vot_tree, prop_nome, id_vot)

    def guarantee_existence_of_proposition(self,
                                           proposicoes, votacoes,
                                           vot_tree, prop_nome, id_vot):
        if prop_nome in proposicoes:
            proposicao = proposicoes[prop_nome]
        else:
            # a prop. nao estava criada ainda, entao devemos tanto criar
            # qnt cadastrar no dicionario.
            proposicao = self.create_proposition(proposicoes, prop_nome,
                                                 vot_tree)
        if self.verbose:
            logger.info('Proposicao %s salva' % proposicao)
        proposicao.save()
        vot = self.create_voting(proposicao, vot_tree, id_vot)
        vot.save()
        votacoes.append(vot)

    def create_proposition(self, proposicoes, prop_nome, vot_tree):
        proposicao = models.Proposicao()
        proposicao.sigla, proposicao.numero, proposicao.ano = self. \
            tipo_num_anoDePropNome(prop_nome)
        proposicao.ementa = vot_tree.get('Ementa')
        proposicao.casa_legislativa = self.cmsp
        proposicoes[prop_nome] = proposicao
        return proposicao

    def create_voting(self, prop, vot_tree, id_vot):
        votacao = models.Votacao()
        # só pra criar a chave primária e poder atribuir o votos
        votacao.save()
        votacao.id_vot = id_vot
        votacao.descricao = vot_tree.get(
            'Materia') + ' - ' + vot_tree.get('NotasRodape')
        votacao.data = self.data_da_sessao
        votacao.resultado = vot_tree.get('Resultado')
        self.votos_from_tree(vot_tree, votacao)
        votacao.proposicao = prop
        if self.verbose:
            logger.info('Votacao %s salva' % votacao)
        else:
            self.progresso()
        return votacao

    def sessao_from_tree(self, proposicoes, votacoes, sessao_tree):
        self.data_da_sessao = self.converte_data(sessao_tree.get('Data'))
        for vot_tree in sessao_tree.findall('Votacao'):
            self.votacao_from_tree(proposicoes, votacoes, vot_tree)

    def progresso(self):
        """Indica progresso na tela"""
        sys.stdout.write('x')
        sys.stdout.flush()


class ImportadorCMSP:

    """Salva os dados dos arquivos XML da cmsp no banco de dados"""

    def __init__(self, cmsp, verbose=False):
        """verbose (booleano) -- ativa/desativa prints na tela"""
        self.verbose = verbose
        self.xml_cmsp = XmlCMSP(cmsp, verbose)
        self.proposicoes = {}
        self.votacoes = []

    def importar_de_url(self, xml_url):
        text = ''
        try:
            xml_text = requests.get(xml_url).text
            self.importar_de(xml_text)
        except RequestException as error:
            logger.error("%s ao acessar %s", error, xml_url)

    def importar_de(self, xml_text):
        """Salva no banco de dados do Django e retorna lista das votações"""
        if self.verbose:
            logger.info("importando de: " + str(xml_file))

        tree = etree.fromstring(xml_text)
        self.analisar_xml(self.proposicoes, self.votacoes, tree)
        return self.votacoes

    def analisar_xml(self, proposicoes, votacoes, tree):
        for sessao_tree in tree.findall('Sessao'):
            self.xml_cmsp.sessao_from_tree(proposicoes, votacoes, sessao_tree)


def main():
    logger.info('IMPORTANDO DADOS DA CAMARA MUNICIPAL DE SAO PAULO (CMSP)')
    gerador_casa = GeradorCasaLegislativa()
    cmsp = gerador_casa.gerar_cmsp()
    importer = ImportadorCMSP(cmsp)
    logger.info(
        'IMPORTANDO CHEFES EXECUTIVOS DA CAMARA MUNICIPAL DE SÃO PAULO')
    importer_chefe = ImportadorChefesExecutivos(
        NOME_CURTO, 'PrefeitosSP', 'PrefeitoSP', XML_FILE)
    importer_chefe.importar_chefes()
    for ano in ANOS_DISPONIVEIS:
        xml_url = XML_URL % ano
        importer.importar_de_url(xml_url)
    logger.info('Importacao dos dados da \
                Camara Municipal de Sao Paulo (CMSP) terminada')
