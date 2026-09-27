# -*- coding: utf-8 -*-
"""L'identifiant et le mot de passe du serveur des mises à jour (3.5.0, D-85)
— sans Qt.

Le bord (24/09/2026) : le zip et son empreinte sur un serveur personnel,
« protégé par .htaccess, que Carène pourrait passer ».

**Jamais dans un fichier.** La configuration du poste (`carene.config.json`)
vit à côté du programme, donc sur le NAS, lisible par tous les postes, et
part dans les copies du dossier : un mot de passe n'a rien à y faire. Sous
Windows, il est confié au **gestionnaire d'identification** de l'utilisateur
(le même coffre que les lecteurs réseau), une entrée générique
« Carene mise a jour <hôte> ». Chaque poste le saisit une fois ; il ne quitte
pas ce poste.

Ailleurs que sous Windows, ou si le coffre refuse, il ne vit que le temps de
la session (`_SESSION`) : Carène le redemandera au prochain lancement.

`MEMOIRE_SEULE` (tests) : ne jamais toucher au vrai coffre.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

MEMOIRE_SEULE = bool(os.environ.get("CARENE_IDENTIFIANTS_MEMOIRE"))
_SESSION: dict = {}
PREFIXE = "Carene mise a jour "
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


def hote_de(adresse: str) -> str:
    """« http://theptitprince.fr/carene » → « theptitprince.fr »."""
    return (urlparse(str(adresse or "")).netloc or str(adresse or "")).lower()


def _cible(adresse):
    return PREFIXE + hote_de(adresse)


# ------------------------------------------------------------ coffre Windows
def _api():
    """Les fonctions du coffre (advapi32), ou None hors de Windows."""
    if os.name != "nt" or MEMOIRE_SEULE:
        return None
    import ctypes
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]
    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    except OSError:
        return None
    pcred = ctypes.POINTER(CREDENTIALW)
    advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(pcred)]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    advapi.CredFree.restype = None
    return ctypes, CREDENTIALW, pcred, advapi


def lire(adresse: str):
    """(identifiant, mot_de_passe) pour ce serveur, ou (None, None)."""
    cible = _cible(adresse)
    if cible in _SESSION:
        return _SESSION[cible]
    api = _api()
    if api is None:
        return None, None
    ctypes, _C, pcred, advapi = api
    p = pcred()
    if not advapi.CredReadW(cible, _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None, None
    try:
        c = p.contents
        taille = int(c.CredentialBlobSize)
        brut = ctypes.string_at(c.CredentialBlob, taille) if taille else b""
        return (c.UserName or ""), brut.decode("utf-16-le")
    finally:
        advapi.CredFree(p)


def enregistrer(adresse: str, identifiant: str, mot_de_passe: str) -> bool:
    """Garde l'identifiant et le mot de passe de ce serveur. Rend True s'ils
    sont dans le coffre de Windows, False s'ils ne vivent que pour la
    session."""
    cible = _cible(adresse)
    _SESSION[cible] = (identifiant, mot_de_passe)
    api = _api()
    if api is None:
        return False
    ctypes, CREDENTIALW, _p, advapi = api
    octets = (mot_de_passe or "").encode("utf-16-le")
    tampon = (ctypes.c_ubyte * max(1, len(octets))).from_buffer_copy(octets or b"\0")
    c = CREDENTIALW()
    c.Type = _CRED_TYPE_GENERIC
    c.TargetName = cible
    c.Comment = "Carène : serveur des mises à jour"
    c.CredentialBlobSize = len(octets)
    c.CredentialBlob = ctypes.cast(tampon, ctypes.POINTER(ctypes.c_ubyte))
    c.Persist = _CRED_PERSIST_LOCAL_MACHINE
    c.UserName = identifiant or ""
    return bool(advapi.CredWriteW(ctypes.byref(c), 0))


def effacer(adresse: str) -> None:
    """Oublie l'identifiant et le mot de passe de ce serveur, partout."""
    cible = _cible(adresse)
    _SESSION.pop(cible, None)
    api = _api()
    if api is not None:
        api[3].CredDeleteW(cible, _CRED_TYPE_GENERIC, 0)
