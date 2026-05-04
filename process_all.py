#!/usr/bin/env python3
"""
Skrypt do przetwarzania wszystkich plików RINEX w projekcie.
Uruchom: python3 process_all.py

Autor: Kuba
"""

import os
import sys
import glob

# Dodaj ścieżkę do rinex_analyzer.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rinex_analyzer import *

def process_file(obs_file, nav_file=None):
    """Przetwarza pojedynczy plik RINEX."""
    print(f'\n{"=" * 60}')
    print(f'Przetwarzanie: {os.path.basename(obs_file)}')
    print(f'{"=" * 60}')

    # Parsuj plik obserwacyjny
    print('  Parsowanie pliku obserwacyjnego...')
    try:
        header, epochs = parse_rinex_obs(obs_file)
    except Exception as e:
        print(f'  BŁĄD: {e}')
        return False

    print(f'  Znaleziono {len(epochs)} epok')
    if not epochs:
        print('  Brak danych obserwacyjnych!')
        return False

    # Szukaj pliku nawigacyjnego
    if nav_file is None or not os.path.exists(nav_file):
        nav_file = find_nav_file(obs_file)

    ephemerides = []
    if nav_file and os.path.exists(nav_file):
        print(f'  Parsowanie pliku nawigacyjnego: {os.path.basename(nav_file)}...')
        try:
            ephemerides = parse_rinex_nav(nav_file)
            print(f'  Znaleziono {len(ephemerides)} ephemeris')
        except Exception as e:
            print(f'  Ostrzeżenie: {e}')

    # Pozycja obserwatora
    obs_pos = header.get('approx_pos')

    # Oblicz DOP
    dop_data = None
    if ephemerides and obs_pos:
        print('  Obliczanie DOP...')
        dop_data = compute_dop(epochs, ephemerides, obs_pos)
        if dop_data:
            print(f'  Obliczono DOP dla {len(dop_data)} epok')

    # Statystyki
    print('  Obliczanie statystyk...')
    stats = compute_statistics(epochs, header, dop_data)
    print_statistics(stats)

    # Generuj wykresy
    print('\n  Generowanie wykresów...')
    output_dir = os.path.join(os.path.dirname(obs_file) or '.',
                              'plots_' + os.path.splitext(os.path.basename(obs_file))[0])
    os.makedirs(output_dir, exist_ok=True)

    plot_satellite_visibility(epochs, output_dir)
    plot_satellite_visibility_by_system(epochs, output_dir)
    plot_snr_time(epochs, header, output_dir)

    if ephemerides and obs_pos:
        plot_skyplot(epochs, ephemerides, obs_pos, output_dir)
        plot_dop(epochs, ephemerides, obs_pos, output_dir)
        plot_snr_elevation(epochs, ephemerides, obs_pos, header, output_dir)

    print(f'\n  ✅ Wykresy zapisane w: {output_dir}')
    return True


def main():
    print('=' * 60)
    print('  RINEX Analyzer - Przetwarzanie wszystkich plików')
    print('=' * 60)

    # Definicje plików do przetworzenia
    files_to_process = [
        # Septentrio PolaRx5 (stacjonarny)
        {
            'obs': 'GNSS_Data_OAUP_20260416/01_Pilares_PolaRx5/SEPT00PRT_R_20261061545_19M_01S_MO.rnx',
            'nav': 'GNSS_Data_OAUP_20260416/01_Pilares_PolaRx5/SEPT00PRT_R_20261061545_19M_MN.rnx',
            'name': 'Septentrio PolaRx5 - sesja 1'
        },
        {
            'obs': 'GNSS_Data_OAUP_20260416/01_Pilares_PolaRx5/SEPT00PRT_R_20261061609_19M_01S_MO.rnx',
            'nav': 'GNSS_Data_OAUP_20260416/01_Pilares_PolaRx5/SEPT00PRT_R_20261061609_19M_MN.rnx',
            'name': 'Septentrio PolaRx5 - sesja 2'
        },
        {
            'obs': 'GNSS_Data_OAUP_20260416/01_Pilares_PolaRx5/SEPT00PRT_R_20261061630_14M_01S_MO.rnx',
            'nav': 'GNSS_Data_OAUP_20260416/01_Pilares_PolaRx5/SEPT00PRT_R_20261061630_14M_MN.rnx',
            'name': 'Septentrio PolaRx5 - sesja 3'
        },
        # Xiaomi Mi8 Smartphone
        {
            'obs': 'GNSS_Data_OAUP_20260416/01_Pilares_Smartphone_Mi8/PL2106P.26o',
            'name': 'Xiaomi Mi8 - PL2106P'
        },
        {
            'obs': 'GNSS_Data_OAUP_20260416/01_Pilares_Smartphone_Mi8/PL4106P.26o',
            'name': 'Xiaomi Mi8 - PL4106P'
        },
        {
            'obs': 'GNSS_Data_OAUP_20260416/01_Pilares_Smartphone_Mi8/PL6106Q.26o',
            'name': 'Xiaomi Mi8 - PL6106Q'
        },
        # EMLID Reach M2
        {
            'obs': 'GNSS_Data_OAUP_20260416/02_Marcas_Reach_M2/reachFCUP_raw_20260416151741.obs',
            'nav': 'GNSS_Data_OAUP_20260416/02_Marcas_Reach_M2/reachFCUP_raw_20260416151741.nav',
            'name': 'EMLID Reach M2 - sesja 1'
        },
        {
            'obs': 'GNSS_Data_OAUP_20260416/02_Marcas_Reach_M2/reachFCUP_raw_20260416155408.obs',
            'nav': 'GNSS_Data_OAUP_20260416/02_Marcas_Reach_M2/reachFCUP_raw_20260416155408.nav',
            'name': 'EMLID Reach M2 - sesja 2'
        },
        {
            'obs': 'GNSS_Data_OAUP_20260416/02_Marcas_Reach_M2/reachFCUP_raw_20260416161427.obs',
            'nav': 'GNSS_Data_OAUP_20260416/02_Marcas_Reach_M2/reachFCUP_raw_20260416161427.nav',
            'name': 'EMLID Reach M2 - sesja 3'
        },
        # Septentrio PolaRx5 (kinematyczny)
        {
            'obs': 'GNSS_Data_OAUP_20260416/03_Cinematico_PolaRx5/SEPT00PRT_R_20261061522_15M_01S_MO.rnx',
            'nav': 'GNSS_Data_OAUP_20260416/03_Cinematico_PolaRx5/SEPT00PRT_R_20261061522_15M_MN.rnx',
            'name': 'Septentrio PolaRx5 - kinematyczny 1'
        },
        {
            'obs': 'GNSS_Data_OAUP_20260416/03_Cinematico_PolaRx5/SEPT00PRT_R_20261061648_08M_01S_MO.rnx',
            'nav': 'GNSS_Data_OAUP_20260416/03_Cinematico_PolaRx5/SEPT00PRT_R_20261061648_08M_MN.rnx',
            'name': 'Septentrio PolaRx5 - kinematyczny 2'
        },
    ]

    success = 0
    for file_info in files_to_process:
        obs_path = file_info['obs']
        if not os.path.exists(obs_path):
            print(f'\n  ⚠️ Plik nie istnieje: {obs_path}')
            continue

        nav_path = file_info.get('nav')
        print(f'\n▶ {file_info["name"]}')
        if process_file(obs_path, nav_path):
            success += 1

    print(f'\n{"=" * 60}')
    print(f'  Przetworzono pomyślnie: {success}/{len(files_to_process)} plików')
    print(f'{"=" * 60}')


if __name__ == '__main__':
    main()
