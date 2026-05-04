#!/usr/bin/env python3
"""
RINEX Analyzer - analiza plików obserwacyjnych GNSS (RINEX)
Generuje wykresy i statystyki podobne do RTKPLOT.

Użycie:
    python3 rinex_analyzer.py <plik_observacyjny> [plik_nawigacyjny]

Jeśli nie podano pliku nawigacyjnego, skrypt szuka go automatycznie.

Autor: Kuba
"""

import sys
import os
import re
import glob
import math
import numpy as np
import matplotlib
# Użyj backendu nieinteraktywnego (działa bez Tkinter)
import os
if 'DISPLAY' not in os.environ:
    matplotlib.use('Agg')
else:
    try:
        matplotlib.use('TkAgg')
    except:
        matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.dates import date2num, num2date
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# KONSTANTY
# ============================================================
# Systemy GNSS i ich oznaczenia w RINEX
GNSS_SYSTEMS = {
    'G': 'GPS',
    'R': 'GLONASS',
    'E': 'Galileo',
    'C': 'BeiDou',
    'J': 'QZSS',
    'S': 'SBAS',
    'I': 'IRNSS',
}

# Stałe fizyczne
OMEGA_E_DOT = 7.2921151467e-5  # prędkość kątowa Ziemi [rad/s]
GM_GPS = 3.986005e14           # stała grawitacyjna GPS [m^3/s^2]
GM_GAL = 3.986004418e14        # stała grawitacyjna Galileo
GM_BDS = 3.986004418e14        # stała grawitacyjna BeiDou
GM_GLO = 3.986004418e14        # stała grawitacyjna GLONASS
C_LIGHT = 2.99792458e8         # prędkość światła [m/s]

GPS_WEEK_EPOCH = datetime(1980, 1, 6)

# Kolory dla systemów GNSS
SYSTEM_COLORS = {
    'G': '#FF0000',  # GPS - czerwony
    'R': '#0040FF',  # GLONASS - niebieski
    'E': '#00B050',  # Galileo - zielony
    'C': '#FF00FF',  # BeiDou - magenta
    'J': '#FF8000',  # QZSS - pomarańczowy
    'S': '#800080',  # SBAS - fioletowy
    'I': '#A0A0A0',  # IRNSS - szary
}


# ============================================================
# PARSER RINEX OBSERVATION
# ============================================================

def parse_rinex_obs_header(f):
    """Parsuje nagłówek pliku RINEX obserwacyjnego."""
    header = {
        'version': None,
        'type': None,
        'sys_obs_types': {},    # {system: [obs_types]}
        'obs_count': {},        # {system: count}
        'approx_pos': None,     # APPROX POSITION XYZ
        'interval': None,
        'time_first': None,
        'time_last': None,
        'marker_name': '',
        'rec_type': '',
        'ant_type': '',
        'glonass_slot_frq': {},  # {sat: freq} np. 'R01': 1
        'phase_shifts': [],
    }

    while True:
        line = f.readline()
        if not line:
            break
        line = line.rstrip('\n\r')
        if len(line) < 20:
            continue

        label = line[20:].strip() if len(line) > 20 else line.strip()

        if 'RINEX VERSION / TYPE' in label:
            header['version'] = float(line[:9].strip())
            header['type'] = line[20:40].strip()
        elif 'MARKER NAME' in label:
            header['marker_name'] = line[:20].strip()
        elif 'REC # / TYPE / VERS' in label:
            header['rec_type'] = line[20:40].strip()
        elif 'ANT # / TYPE' in label:
            header['ant_type'] = line[20:40].strip()
        elif 'APPROX POSITION XYZ' in label:
            parts = line[:60].split()
            if len(parts) >= 3:
                header['approx_pos'] = tuple(float(x) for x in parts[:3])
        elif 'ANTENNA: DELTA H/E/N' in label:
            parts = line[:60].split()
            if len(parts) >= 3:
                header['ant_delta'] = tuple(float(x) for x in parts[:3])
        elif 'INTERVAL' in label:
            header['interval'] = float(line[:10].strip())
        elif 'TIME OF FIRST OBS' in label:
            parts = line[:43].split()
            if len(parts) >= 6:
                sec = float(parts[5])
                usec = int((sec - int(sec)) * 1e6)
                header['time_first'] = datetime(int(parts[0]), int(parts[1]),
                                                int(parts[2]), int(parts[3]),
                                                int(parts[4]), int(sec), usec)
        elif 'TIME OF LAST OBS' in label:
            parts = line[:43].split()
            if len(parts) >= 6:
                sec = float(parts[5])
                usec = int((sec - int(sec)) * 1e6)
                header['time_last'] = datetime(int(parts[0]), int(parts[1]),
                                               int(parts[2]), int(parts[3]),
                                               int(parts[4]), int(sec), usec)
        elif 'SYS / # / OBS TYPES' in label:
            # Sprawdź czy to linia nagłówka (system w kol 0) czy kontynuacja
            sys_code = line[0]
            if sys_code.isalpha() and sys_code != ' ':
                # Nowa linia nagłówka
                count_str = line[3:6].strip()
                count = int(count_str) if count_str else 0
                obs_types_line = line[7:60].split()
                if sys_code not in header['sys_obs_types']:
                    header['sys_obs_types'][sys_code] = []
                    header['obs_count'][sys_code] = count
                header['sys_obs_types'][sys_code].extend(obs_types_line)
            else:
                # Linia kontynuacji (dalsze typy obserwacji dla tego samego systemu)
                # Znajdź ostatnio dodany system
                obs_types_line = line[7:60].split()
                if header['sys_obs_types']:
                    last_sys = list(header['sys_obs_types'].keys())[-1]
                    header['sys_obs_types'][last_sys].extend(obs_types_line)
        elif 'GLONASS SLOT / FRQ #' in label:
            # Format: " 24 R01  1 R02 -4 R03  5 ..."
            # lub " 8 R04  6 R05  1 R06 -4 ..."
            parts = line.strip().split()
            i = 0
            while i < len(parts):
                # Szukaj satelitów w formacie R01, R02, ... (3 znaki, litera+2 cyfry)
                if len(parts[i]) == 3 and parts[i][0] in 'RGECJ' and parts[i][1:].isdigit() and i + 1 < len(parts):
                    sat = parts[i]
                    try:
                        freq = int(parts[i + 1])
                        header['glonass_slot_frq'][sat] = freq
                        i += 2
                    except ValueError:
                        i += 1
                else:
                    i += 1
        elif 'SYS / PHASE SHIFT' in label:
            header['phase_shifts'].append(line.strip())
        elif 'END OF HEADER' in label:
            break

    return header


def parse_rinex_obs_epoch(line, header):
    """Parsuje linię epoki RINEX v3.x."""
    # Format v3.x: > 2026 04 16 15 17 18.9996899  0 22
    # Format v4.x: > 2026 04 16 15 45 37.0000000  0 14
    parts = line.strip().split()
    if len(parts) < 7:
        return None, 0, None

    year = int(parts[0])
    month = int(parts[1])
    day = int(parts[2])
    hour = int(parts[3])
    minute = int(parts[4])
    second = float(parts[5])
    flag = int(parts[6]) if len(parts) > 6 else 0
    num_sats = int(parts[7]) if len(parts) > 7 else 0

    sec_int = int(second)
    usec = int((second - sec_int) * 1e6)
    epoch_time = datetime(year, month, day, hour, minute, sec_int, usec)
    return epoch_time, num_sats, flag


def parse_rinex_obs_data(lines, header):
    """
    Parsuje dane obserwacyjne RINEX (po linii epoki).
    Zwraca słownik {sat: {obs_type: value}}.
    """
    result = {}
    sys_obs_types = header.get('sys_obs_types', {})

    for line in lines:
        if not line.strip():
            continue

        # Określenie systemu i numeru satelity (3 znaki: np. "G01", "R04", "E15")
        sat = line[:3].strip()
        if not sat or len(sat) > 3 or not sat[0].isalpha():
            continue

        sys_code = sat[0]
        if sys_code not in sys_obs_types:
            continue

        obs_types = sys_obs_types[sys_code]
        obs_data = {}

        # W RINEX v3.x i v4.x obserwacje są zapisywane w polach 16-znakowych:
        # 14 znaków wartości + LLI/SSI. Część plików v4 zachowuje ten sam układ,
        # więc rozbijanie po białych znakach przesuwa kolumny i miesza typy danych.
        data_str = line[3:]  # pomiń identyfikator satelity
        for obs_idx, obs_type in enumerate(obs_types):
            pos = obs_idx * 16
            field = data_str[pos:pos + 16]
            if not field:
                break

            # Wartość obserwacji zajmuje pierwsze 14 znaków pola.
            value_str = field[:14].strip()
            if not value_str:
                continue

            try:
                obs_data[obs_type] = float(value_str.replace('D', 'E').replace('d', 'e'))
            except ValueError:
                continue

        if obs_data:
            result[sat] = obs_data

    return result


def parse_rinex_obs(filename):
    """
    Główna funkcja parsująca plik RINEX obserwacyjny.
    Zwraca (header, epochs) gdzie epochs to lista (time, {sat: {obs: value}}).
    """
    epochs = []

    with open(filename, 'r', encoding='utf-8', errors='replace') as f:
        header = parse_rinex_obs_header(f)

        # Czytaj dane epok
        current_epoch_lines = []
        current_time = None
        current_num_sats = 0

        for line in f:
            line = line.rstrip('\n\r')
            if not line.strip():
                continue

            if line.startswith('> '):
                # Poprzednia epoka
                if current_epoch_lines and current_time is not None:
                    obs_data = parse_rinex_obs_data(current_epoch_lines, header)
                    epochs.append((current_time, obs_data))

                # Nowa epoka
                line = line[2:]  # usuń '> '
                current_time, current_num_sats, flag = parse_rinex_obs_epoch(line, header)
                current_epoch_lines = []
            else:
                current_epoch_lines.append(line)

        # Ostatnia epoka
        if current_epoch_lines and current_time is not None:
            obs_data = parse_rinex_obs_data(current_epoch_lines, header)
            epochs.append((current_time, obs_data))
    
    # Jeśli TIME OF LAST OBS nie było w nagłówku, wylicz z ostatniej epoki
    if header['time_last'] is None and epochs:
        header['time_last'] = epochs[-1][0]

    return header, epochs


# ============================================================
# PARSER RINEX NAVIGATION (GPS/Galileo/BeiDou)
# ============================================================

def parse_rinex_nav(filename):
    """
    Parsuje plik RINEX nawigacyjny.
    Zwraca (ephemerides, ion_count, sto_count, non_eph_records).
    """
    ephemerides = []
    non_eph_records = []
    ion_count = 0
    sto_count = 0

    with open(filename, 'r', encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()

    start_idx = 0
    for i, line in enumerate(all_lines):
        if 'END OF HEADER' in (line[20:].strip() if len(line) > 20 else line.strip()):
            start_idx = i + 1
            break

    data_lines = []
    pending_msg_type = None
    skip_next = False
    for line in all_lines[start_idx:]:
        line = line.rstrip('\n\r')
        if not line.strip():
            continue
        if line.startswith('> EPH'):
            eph_parts = line.split()
            # Format: > EPH PRN MSGTYPE (np. '> EPH G01 LNAV' -> msg_type='LNAV')
            pending_msg_type = eph_parts[3] if len(eph_parts) >= 4 else 'unknown'
            skip_next = False
            continue
        if line.startswith('> ION'):
            non_eph_records.append(line)
            ion_count += 1
            skip_next = True
            continue
        if line.startswith('> STO'):
            non_eph_records.append(line)
            sto_count += 1
            skip_next = True
            continue
        if line.startswith('> '):
            non_eph_records.append(line)
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        # Store the line together with its message type
        data_lines.append((line, pending_msg_type))

    # Grupuj linie w zestawy ephemeris
    i = 0
    while i < len(data_lines):
        line, msg_type = data_lines[i]
        parts = line.split()
        if len(parts) < 8:
            i += 1
            continue

        prn = parts[0]
        # Sprawdź czy to poprawny identyfikator satelity
        if not (len(prn) == 3 and prn[0] in 'GRECJSI' and prn[1:].isdigit()):
            i += 1
            continue

        try:
            year = int(parts[1])
            month = int(parts[2])
            day = int(parts[3])
            hour = int(parts[4])
            minute = int(parts[5])
            sec = float(parts[6])
            sec_int = int(sec)
            usec = int((sec - sec_int) * 1e6)
            toc = datetime(year, month, day, hour, minute, sec_int, usec)
        except (ValueError, IndexError):
            i += 1
            continue

        # Określ ile linii danych spodziewamy się dla danego systemu
        sys_code = prn[0]
        if sys_code == 'S':
            # SBAS: krótki format ephemeris
            num_lines = 4  # 1 header + 3 data
        elif sys_code == 'R':
            # GLONASS: 5 linii
            num_lines = 5  # 1 header + 4 data
        else:
            # GPS, Galileo, BeiDou, QZSS: standard 8 linii
            num_lines = 8  # 1 header + 7 data

        # Zbierz linie dla tego satelity
        # Infer message type if not set from > EPH header
        if msg_type is None or msg_type == 'unknown':
            # Infer from system type and line count
            inferred = {
                'G': 'LNAV',
                'R': 'FDMA',
                'E': 'INAV',
                'C': 'D1',
                'S': 'SBAS',
                'J': 'LNAV',
            }
            msg_type = inferred.get(sys_code, 'unknown')
            if msg_type != 'unknown':
                msg_type = f'{msg_type} (inferred)'
        
        ephem_data = {
            'prn': prn,
            'toc': toc,
            'msg_type': msg_type,
            'raw': [line],
        }

        for j in range(1, num_lines):
            if i + j < len(data_lines):
                next_line, _ = data_lines[i + j]
                next_parts = next_line.split()
                # Sprawdź czy to nie jest nowa satelita (linia z PRNem)
                if len(next_parts) >= 8:
                    next_prn = next_parts[0]
                    if len(next_prn) == 3 and next_prn[0] in 'GRECJSI' and next_prn[1:].isdigit():
                        # To nowa satelita - zatrzymaj się przed nią
                        break
                ephem_data['raw'].append(next_line)

        i += len(ephem_data['raw'])

        # Parsuj dane ephemeris
        try:
            parsed = parse_ephemeris_data(ephem_data['raw'])
            ephem_data.update(parsed)
            # Sprawdź czy dane są sensowne (np. A > 0 dla GPS)
            A = ephem_data.get('A', 0)
            if sys_code not in ('S',) or A > 0:
                ephemerides.append(ephem_data)
        except Exception as e:
            pass

    return ephemerides, ion_count, sto_count, non_eph_records


def parse_ephemeris_data(raw_lines):
    """
    Parsuje surowe linie ephemeris RINEX nawigacyjnego.
    Format GPS LNAV:
    Linia 1: PRN, epoch, af0, af1, af2
    Linia 2: IODE, Crs, Delta_n, M0
    Linia 3: Cuc, e, Cus, sqrt(A)
    Linia 4: Toe, Cic, Omega0, Cis
    Linia 5: i0, Crc, omega, Omega_dot
    Linia 6: i_dot, L2 codes, GPS week, L2 P flag
    Linia 7: SV acc, SV health, TGD, IODC
    Linia 8: Transmission time, fit interval
    """
    def parse_double(s):
        """Konwertuje liczbę w notacji Fortran D (np. .123D+03) na float."""
        s = s.replace('D', 'E').replace('d', 'e')
        return float(s)
    
    def extract_numbers(line):
        """Wyodrębnia wszystkie liczby zmiennoprzecinkowe z linii.
        Obsługuje zarówno format z spacjami (Reach) jak i połączony (Septentrio)."""
        numbers = []
        # Najpierw spróbuj prostego split
        parts = line.split()
        for p in parts:
            # Sprawdź czy to może być połączona liczba (np. "1.23E-04-5.67E-12")
            nums = re.findall(r'[-+]?\d*\.?\d+(?:[DdEe][-+]?\d+)?', p)
            for n in nums:
                if n and n != '.' and n != '+' and n != '-':
                    try:
                        numbers.append(parse_double(n))
                    except ValueError:
                        pass
        if not numbers:
            # Spróbuj regex bezpośrednio na całej linii
            nums = re.findall(r'[-+]?\d*\.?\d+(?:[DdEe][-+]?\d+)?', line)
            for n in nums:
                if n and n != '.' and n != '+' and n != '-':
                    try:
                        numbers.append(parse_double(n))
                    except ValueError:
                        pass
        return numbers

    data = {}
    if len(raw_lines) < 1:
        return data

    # Linia 1: PRN, epoch, af0, af1, af2
    parts = raw_lines[0].split()
    if len(parts) >= 7:
        data['prn'] = parts[0]
        data['toc_str'] = ' '.join(parts[1:7])
        
        # Wyodrębnij wartości numeryczne
        values = extract_numbers(' '.join(parts[7:]))
        
        if len(values) >= 1:
            data['af0'] = values[0]
        if len(values) >= 2:
            data['af1'] = values[1]
        if len(values) >= 3:
            data['af2'] = values[2]
        else:
            data['af2'] = 0.0
    else:
        return data

    # Linia 2: IODE, Crs, Delta_n, M0
    if len(raw_lines) >= 2:
        values = extract_numbers(raw_lines[1])
        if len(values) >= 4:
            data['Crs'] = values[1]
            data['Delta_n'] = values[2]
            data['M0'] = values[3]

    # Linia 3: Cuc, e, Cus, sqrt(A)
    if len(raw_lines) >= 3:
        values = extract_numbers(raw_lines[2])
        if len(values) >= 4:
            data['Cuc'] = values[0]
            data['e'] = values[1]
            data['Cus'] = values[2]
            data['sqrt_A'] = values[3]
            data['A'] = data['sqrt_A'] ** 2

    # Linia 4: Toe, Cic, Omega0, Cis
    if len(raw_lines) >= 4:
        values = extract_numbers(raw_lines[3])
        if len(values) >= 4:
            data['Toe'] = values[0]
            data['Cic'] = values[1]
            data['Omega0'] = values[2]
            data['Cis'] = values[3]

    # Linia 5: i0, Crc, omega, Omega_dot
    if len(raw_lines) >= 5:
        values = extract_numbers(raw_lines[4])
        if len(values) >= 4:
            data['i0'] = values[0]
            data['Crc'] = values[1]
            data['omega'] = values[2]
            data['Omega_dot'] = values[3]

    # Linia 6: i_dot, L2 codes, GPS week, L2 P flag
    if len(raw_lines) >= 6:
        values = extract_numbers(raw_lines[5])
        if len(values) >= 1:
            data['i_dot'] = values[0]
        if len(values) >= 4:
            data['GPS_week'] = values[3]

    # Linia 7: SV acc, SV health, TGD, IODC
    if len(raw_lines) >= 7:
        values = extract_numbers(raw_lines[6])
        if len(values) >= 3:
            data['TGD'] = values[2]

    return data


# ============================================================
# OBLICZENIA POZYCJI SATELIT (GPS / Keplerian)
# ============================================================

def compute_glonass_satellite_position(ephem, t):
    """
    Oblicza pozycję satelity GLONASS w układzie ECEF (PZ-90) w danym czasie t.
    GLONASS używa jawnie podanego wektora stanu (X, VX, AX) w km, km/s, km/s^2.
    
    Format GLONASS ephemeris w RINEX:
      Line 1: PRN, year, month, day, hour, min, sec, tau_n, gamma_n, tk
      Line 2: X (km), VX (km/s), AX (km/s^2), health
      Line 3: Y (km), VY (km/s), AY (km/s^2), freq_num
      Line 4: Z (km), VZ (km/s), AZ (km/s^2), age_info
    
    Zwraca (x, y, z) w metrach.
    """
    raw = ephem.get('raw', [])
    if len(raw) < 4:
        return None
    
    def parse_double(s):
        s = s.replace('D', 'E').replace('d', 'e')
        return float(s)
    
    try:
        # Lines 1-3 (indices 1, 2, 3): state vector (X, Y, Z in km, VX, VY, VZ in km/s, AX, AY, AZ in km/s^2)
        # Each line has 4 values: position, velocity, acceleration, extra_param
        # We only take the first 3 values from each line
        state = []
        for line_idx in range(1, 4):
            if line_idx >= len(raw):
                break
            nums = re.findall(r'[-+]?\d*\.?\d+(?:[DdEe][-+]?\d+)?', raw[line_idx])
            # Skip extra parameters (health, freq_num, age_info) - take only first 3 values
            count = 0
            for n in nums:
                if n and n not in ('.', '+', '-') and count < 3:
                    try:
                        state.append(parse_double(n))
                        count += 1
                    except:
                        pass
        
        if len(state) < 9:
            return None
        
        # State vector components (convert km to m, km/s to m/s, km/s^2 to m/s^2)
        X = state[0] * 1000      # km -> m
        VX = state[1] * 1000     # km/s -> m/s
        AX = state[2] * 1000     # km/s^2 -> m/s^2
        Y = state[3] * 1000
        VY = state[4] * 1000
        AY = state[5] * 1000
        Z = state[6] * 1000
        VZ = state[7] * 1000
        AZ = state[8] * 1000
        
        # Epoch time from line 0
        epoch_parts = raw[0].split()
        epoch_year = int(epoch_parts[1])
        epoch_month = int(epoch_parts[2])
        epoch_day = int(epoch_parts[3])
        epoch_hour = int(epoch_parts[4])
        epoch_min = int(epoch_parts[5])
        epoch_sec = float(epoch_parts[6])
        epoch_sec_int = int(epoch_sec)
        epoch_usec = int((epoch_sec - epoch_sec_int) * 1e6)
        
        from datetime import datetime, timedelta
        epoch_dt = datetime(epoch_year, epoch_month, epoch_day, 
                           epoch_hour, epoch_min, epoch_sec_int, epoch_usec)
        
        # t is in seconds since GPS epoch (Jan 6, 1980)
        gps_epoch = datetime(1980, 1, 6)
        target_dt = gps_epoch + timedelta(seconds=t)
        
        delta_t = (target_dt - epoch_dt).total_seconds()
        
        # Propagate position using simplified numerical integration
        # r(t) = r0 + v0 * dt + 0.5 * a0 * dt^2
        x_m = X + VX * delta_t + 0.5 * AX * delta_t * delta_t
        y_m = Y + VY * delta_t + 0.5 * AY * delta_t * delta_t
        z_m = Z + VZ * delta_t + 0.5 * AZ * delta_t * delta_t
        
        return (x_m, y_m, z_m)
        
    except Exception as e:
        return None


def compute_satellite_position(ephem, t):
    """
    Oblicza pozycję satelity w układzie ECEF (WGS-84) w danym czasie t.
    Automatycznie wybiera metodę w zależności od systemu GNSS:
      - GPS, Galileo, BeiDou, QZSS: Keplerian orbital elements
      - GLONASS: state vector propagation
      - SBAS: not supported (returns None)
    Zwraca (x, y, z) w metrach lub None jeśli nie można obliczyć.
    """
    prn = ephem.get('prn', '')
    if prn.startswith('R'):
        # GLONASS: użyj wektora stanu
        return compute_glonass_satellite_position(ephem, t)
    
    # GPS, Galileo, BeiDou, QZSS: Keplerian elements
    if not all(k in ephem for k in ['A', 'e', 'i0', 'Omega0', 'omega',
                                      'M0', 'Delta_n', 'Omega_dot',
                                      'i_dot', 'Toe', 'Cuc', 'Cus',
                                      'Crc', 'Crs', 'Cic', 'Cis']):
        return None

    A = ephem['A']
    e = ephem['e']
    i0 = ephem['i0']
    Omega0 = ephem['Omega0']
    omega = ephem['omega']
    M0 = ephem['M0']
    Delta_n = ephem['Delta_n']
    Omega_dot = ephem['Omega_dot']
    i_dot = ephem['i_dot']
    Toe = ephem['Toe']
    Cuc = ephem['Cuc']
    Cus = ephem['Cus']
    Crc = ephem['Crc']
    Crs = ephem['Crs']
    Cic = ephem['Cic']
    Cis = ephem['Cis']

    # Określ system GNSS
    prn = ephem.get('prn', 'G00')
    sys = prn[0]

    if sys == 'G':
        GM = GM_GPS
        omega_e = OMEGA_E_DOT
    elif sys == 'E':
        GM = GM_GAL
        omega_e = OMEGA_E_DOT
    elif sys == 'C':
        GM = GM_BDS
        omega_e = OMEGA_E_DOT
        # BeiDou ma nieco inne parametry, ale dla uproszczenia...
    else:
        GM = GM_GPS
        omega_e = OMEGA_E_DOT

    # Czas od epoki ephemeris
    # Toe jest w sekundach tygodnia GPS, więc t też musi być w sekundach tygodnia
    # Jeśli t jest w sekundach od epoki GPS, skonwertuj do tygodnia
    if t > 604800 * 2:  # t jest w sekundach od epoki GPS (1980-01-06)
        t_week = t % 604800
    else:
        t_week = t
    tk = t_week - Toe
    # Jeśli różnica jest poza zakresem ±2 tygodnie, przelicz
    if tk > 604800:
        tk -= 604800
    elif tk < -604800:
        tk += 604800

    # Średni ruch
    n0 = math.sqrt(GM / A ** 3)
    n = n0 + Delta_n

    # Anomalia średnia
    Mk = M0 + n * tk

    # Równanie Keplera (anomalia mimośrodowa)
    Ek = Mk
    for _ in range(10):
        Ek_new = Mk + e * math.sin(Ek)
        if abs(Ek_new - Ek) < 1e-12:
            break
        Ek = Ek_new

    # Anomalia prawdziwa
    vk = math.atan2(math.sqrt(1 - e * e) * math.sin(Ek), math.cos(Ek) - e)

    # Argument szerokości
    Phi_k = vk + omega

    # Poprawki harmoniczne
    delta_uk = Cus * math.sin(2 * Phi_k) + Cuc * math.cos(2 * Phi_k)
    delta_rk = Crs * math.sin(2 * Phi_k) + Crc * math.cos(2 * Phi_k)
    delta_ik = Cis * math.sin(2 * Phi_k) + Cic * math.cos(2 * Phi_k)

    # Poprawiony argument szerokości, promień, inklinacja
    uk = Phi_k + delta_uk
    rk = A * (1 - e * math.cos(Ek)) + delta_rk
    ik = i0 + delta_ik + i_dot * tk

    # Pozycja w orbitalnym układzie
    xk_prime = rk * math.cos(uk)
    yk_prime = rk * math.sin(uk)

    # Długość geograficzna węzła wstępującego
    Omega_k = Omega0 + (Omega_dot - omega_e) * tk - omega_e * Toe

    # Pozycja ECEF
    x = xk_prime * math.cos(Omega_k) - yk_prime * math.cos(ik) * math.sin(Omega_k)
    y = xk_prime * math.sin(Omega_k) + yk_prime * math.cos(ik) * math.cos(Omega_k)
    z = yk_prime * math.sin(ik)

    return (x, y, z)


def rotate_satellite_for_earth_rotation(sat_pos, travel_time):
    """
    Obraca pozycję satelity z chwili transmisji do układu ECEF w chwili odbioru.
    To poprawka Sagnaca wynikająca z obrotu Ziemi podczas propagacji sygnału.
    """
    if sat_pos is None:
        return None

    alpha = OMEGA_E_DOT * travel_time
    cos_a = math.cos(alpha)
    sin_a = math.sin(alpha)
    x, y, z = sat_pos

    x_rot = cos_a * x + sin_a * y
    y_rot = -sin_a * x + cos_a * y
    return (x_rot, y_rot, z)


def compute_satellite_clock_correction(ephem, t):
    """
    Oblicza poprawkę zegara satelity w sekundach.
    Dla satelitów keplerowskich dodaje też poprawkę relatywistyczną.
    """
    af0 = ephem.get('af0', 0.0)
    af1 = ephem.get('af1', 0.0)
    af2 = ephem.get('af2', 0.0)
    toc = ephem.get('toc')

    dt = 0.0
    if toc is not None:
        if t > 604800 * 2:
            target_dt = GPS_WEEK_EPOCH + timedelta(seconds=t)
            dt = (target_dt - toc).total_seconds()
        else:
            toe = ephem.get('Toe', 0.0)
            dt = t - toe

    # Normalizacja do około jednego tygodnia GPS
    while dt > 302400:
        dt -= 604800
    while dt < -302400:
        dt += 604800

    clock_corr = af0 + af1 * dt + af2 * dt * dt

    prn = ephem.get('prn', '')
    if prn.startswith(('G', 'E', 'C', 'J')):
        sqrt_A = ephem.get('sqrt_A')
        e = ephem.get('e')
        M0 = ephem.get('M0')
        Delta_n = ephem.get('Delta_n')
        Toe = ephem.get('Toe')
        if None not in (sqrt_A, e, M0, Delta_n, Toe):
            if prn.startswith('G'):
                GM = GM_GPS
            elif prn.startswith(('E', 'C')):
                GM = GM_GAL
            else:
                GM = GM_GPS

            A = sqrt_A ** 2
            n0 = math.sqrt(GM / A ** 3)
            n = n0 + Delta_n
            t_week = t % 604800 if t > 604800 * 2 else t
            tk = t_week - Toe
            while tk > 302400:
                tk -= 604800
            while tk < -302400:
                tk += 604800

            Mk = M0 + n * tk
            Ek = Mk
            for _ in range(10):
                Ek_new = Mk + e * math.sin(Ek)
                if abs(Ek_new - Ek) < 1e-12:
                    break
                Ek = Ek_new

            clock_corr += -2.0 * math.sqrt(GM) * e * sqrt_A * math.sin(Ek) / (C_LIGHT ** 2)

    return clock_corr


def compute_transmission_satellite_state(ephem, recv_time_gps, receiver_pos, pseudorange):
    """
    Oblicza pozycję satelity w chwili transmisji i obraca ją do układu ECEF
    z chwili odbioru. Zwraca (sat_pos_corrected, sat_clock_err, travel_time).
    """
    tau = pseudorange / C_LIGHT

    for _ in range(3):
        tx_time_gps = recv_time_gps - tau
        sat_clock_err = compute_satellite_clock_correction(ephem, tx_time_gps)
        tau = (pseudorange + sat_clock_err * C_LIGHT) / C_LIGHT

    tx_time_gps = recv_time_gps - tau
    sat_clock_err = compute_satellite_clock_correction(ephem, tx_time_gps)
    sat_pos_tx = compute_satellite_position(ephem, tx_time_gps)
    sat_pos = rotate_satellite_for_earth_rotation(sat_pos_tx, tau)

    if sat_pos is None or receiver_pos is None:
        return sat_pos, sat_clock_err, tau

    return sat_pos, sat_clock_err, tau


def compute_azimuth_elevation(sat_pos, obs_pos):
    """
    Oblicza azymut i elewację satelity względem obserwatora.
    sat_pos: (x, y, z) ECEF satelity
    obs_pos: (x, y, z) ECEF obserwatora
    Zwraca (azimuth, elevation) w stopniach.
    """
    if sat_pos is None or obs_pos is None:
        return None, None

    dx = sat_pos[0] - obs_pos[0]
    dy = sat_pos[1] - obs_pos[1]
    dz = sat_pos[2] - obs_pos[2]

    # Odległość
    rho = math.sqrt(dx * dx + dy * dy + dz * dz)
    if rho == 0:
        return None, None

    # Konwersja ECEF -> ENU (East, North, Up)
    # Najpierw potrzebujemy współrzędnych geodezyjnych obserwatora
    lat, lon, h = ecef_to_geodetic(obs_pos[0], obs_pos[1], obs_pos[2])

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    # Macierz rotacji ECEF -> ENU
    e = -sin_lon * dx + cos_lon * dy
    n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    u = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz

    # Azymut (0-360 stopni)
    az = math.degrees(math.atan2(e, n)) % 360

    # Elewacja
    el = math.degrees(math.atan2(u, math.sqrt(e * e + n * n)))

    return az, el


def ecef_to_geodetic(x, y, z):
    """
    Konwersja ECEF (WGS-84) na współrzędne geodezyjne.
    Zwraca (latitude, longitude, height) w radianach i metrach.
    """
    a = 6378137.0        # półosiowa wielka [m]
    f = 1 / 298.257223563 # spłaszczenie
    e2 = 2 * f - f * f    # pierwszy mimośródeł kwadrat

    lon = math.atan2(y, x)

    # Iteracyjne wyznaczanie szerokości
    p = math.sqrt(x * x + y * y)
    lat = math.atan2(z, p * (1 - e2))

    for _ in range(10):
        sin_lat = math.sin(lat)
        N = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
        h = p / math.cos(lat) - N
        old_lat = lat
        lat = math.atan2(z, p * (1 - e2 * N / (N + h)))
        if abs(lat - old_lat) < 1e-12:
            break

    return lat, lon, h


# ============================================================
# ANALIZA
# ============================================================

def analyze_satellite_visibility(epochs):
    """
    Analizuje widzialność satelitów.
    Zwraca listę (czas, liczba_satelitów, {system: liczba}).
    """
    results = []
    for t, obs in epochs:
        sys_count = defaultdict(int)
        for sat in obs:
            sys_code = sat[0]
            sys_count[sys_code] += 1
        total = len(obs)
        results.append((t, total, dict(sys_count)))
    return results


def analyze_snr(epochs, header):
    """
    Ekstrahuje SNR z danych obserwacyjnych.
    Zwraca listę (czas, sat, system, snr_value, obs_type).
    """
    snr_data = []
    sys_obs_types = header.get('sys_obs_types', {})

    for t, obs in epochs:
        for sat, data in obs.items():
            sys_code = sat[0]
            # Szukaj obserwacji typu S* (SNR)
            if sys_code in sys_obs_types:
                for obs_type in sys_obs_types[sys_code]:
                    if obs_type.startswith('S') and obs_type in data:
                        snr_val = data[obs_type]
                        # SNR w RINEX to wartości od ~15 do ~55 dBHz
                        # Odrzuć wartości > 100 (to mogą być błędnie przypisane fazy/pseudoodległości)
                        if not math.isnan(snr_val) and 10 < snr_val < 100:
                            snr_data.append((t, sat, sys_code, snr_val, obs_type))
    return snr_data


def compute_dop(epochs, ephemerides, obs_pos):
    """
    Oblicza DOP (PDOP, HDOP, VDOP) dla każdej epoki.
    Wymaga nawigacyjnych danych ephemeris.
    """
    dop_data = []

    # Dla każdej epoki, oblicz pozycje satelitów i DOP
    for t, obs in epochs:
        # Znajdź ephemeris dla każdego satelity (najbliższy w czasie)
        sat_positions = []  # lista (az, el)

        for sat in obs:
            sys = sat[0]
            prn = sat

            # Znajdź najnowszy ephemeris dla tego satelity
            matching_eph = [e for e in ephemerides if e.get('prn') == prn]
            if not matching_eph:
                continue

            # Wybierz najbliższy czasowo
            best_eph = min(matching_eph, key=lambda e: abs((t - e['toc']).total_seconds()))

            # Oblicz pozycję satelity
            sat_pos = compute_satellite_position(best_eph, (t - GPS_WEEK_EPOCH).total_seconds())
            if sat_pos is None:
                continue

            # Oblicz azymut i elewację
            az, el = compute_azimuth_elevation(sat_pos, obs_pos)
            if az is None or el is None:
                continue

            if el > 5:  # tylko satelity nad horyzontem (> 5 stopni)
                el_rad = math.radians(el)
                az_rad = math.radians(az)
                sat_positions.append((el_rad, az_rad))

        if len(sat_positions) < 4:
            continue

        # Oblicz macierz DOP
        # H = [cos(el)*sin(az), cos(el)*cos(az), sin(el), 1]
        H = []
        for el_rad, az_rad in sat_positions:
            H.append([
                math.cos(el_rad) * math.sin(az_rad),
                math.cos(el_rad) * math.cos(az_rad),
                math.sin(el_rad),
                1.0
            ])

        H = np.array(H)
        try:
            Q = np.linalg.inv(H.T @ H)
            PDOP = math.sqrt(Q[0, 0] + Q[1, 1] + Q[2, 2])
            HDOP = math.sqrt(Q[0, 0] + Q[1, 1])
            VDOP = math.sqrt(Q[2, 2])
            GDOP = math.sqrt(Q[0, 0] + Q[1, 1] + Q[2, 2] + Q[3, 3])
        except np.linalg.LinAlgError:
            continue

        dop_data.append((t, PDOP, HDOP, VDOP, GDOP, len(sat_positions)))

    return dop_data


def compute_spp_positions(epochs, ephemerides, obs_pos, system='G'):
    """
    Single Point Positioning (SPP) - oblicza pozycję odbiornika dla każdej epoki.
    Używa TYLKO satelitów z jednego systemu GNSS (domyślnie GPS 'G').
    
    Zwraca (positions, failures) gdzie:
      positions: lista (czas, x, y, z, clock_bias, num_sats, pdop)
      failures:  lista (czas, reason_string) dla epok bez rozwiązania
    """
    positions = []
    failures = []
    eph_prns = set(e['prn'] for e in ephemerides)

    for t, obs in epochs:
        sats_used = []
        
        for sat, data in obs.items():
            if sat[0] != system:
                continue
            if sat not in eph_prns:
                continue
            C_val = None
            for k, v in data.items():
                if k.startswith('C') and not math.isnan(v) and v > 0:
                    C_val = v
                    break
            if C_val is None:
                continue
            
            matching = [e for e in ephemerides if e.get('prn') == sat]
            if not matching:
                continue
            best = min(matching, key=lambda e: abs((t - e['toc']).total_seconds()))

            t_gps = (t - GPS_WEEK_EPOCH).total_seconds()
            sat_pos = compute_satellite_position(best, t_gps)
            if sat_pos is None:
                continue
            
            az, el = compute_azimuth_elevation(sat_pos, obs_pos)
            if el is None or el < 10:
                continue
            
            sat_pos_corr, sat_clock_err, travel_time = compute_transmission_satellite_state(
                best, t_gps, obs_pos, C_val
            )
            if sat_pos_corr is None:
                continue

            C_corrected = C_val + sat_clock_err * C_LIGHT
            sats_used.append((sat, sat_pos_corr, C_corrected))
        
        if len(sats_used) < 4:
            failures.append((t, 'Insufficient satellites'))
            continue
        
        if obs_pos:
            x0, y0, z0 = obs_pos
        else:
            x0, y0, z0 = (0, 0, 0)
        
        x, y, z, clock = x0, y0, z0, 0.0
        converged = False
        
        for iteration in range(10):
            A = []
            W = []
            
            for sat, sat_pos, C in sats_used:
                dx = sat_pos[0] - x
                dy = sat_pos[1] - y
                dz = sat_pos[2] - z
                rho = math.sqrt(dx*dx + dy*dy + dz*dz)
                
                if rho < 1e-6:
                    continue
                
                omc = C - (rho + clock * C_LIGHT)
                
                A.append([-dx/rho, -dy/rho, -dz/rho, C_LIGHT])
                W.append([omc])
            
            if len(A) < 4:
                break
            
            A = np.array(A)
            W = np.array(W)
            
            try:
                delta = np.linalg.inv(A.T @ A) @ A.T @ W
                if len(delta.shape) > 1:
                    x += float(delta[0, 0])
                    y += float(delta[1, 0])
                    z += float(delta[2, 0])
                    clock += float(delta[3, 0])
                else:
                    x += float(delta[0])
                    y += float(delta[1])
                    z += float(delta[2])
                    clock += float(delta[3])
                
                if np.linalg.norm(delta[:3]) < 0.001:
                    converged = True
                    break
            except np.linalg.LinAlgError:
                break
        
        if not converged:
            failures.append((t, 'No convergence'))
            continue
        
        try:
            Q = np.linalg.inv(A.T @ A)
            pdop = math.sqrt(Q[0,0] + Q[1,1] + Q[2,2])
        except:
            pdop = 0
        
        positions.append((t, x, y, z, clock, len(sats_used), pdop))
    
    return positions, failures

def count_frequencies(header):
    """
    Zlicza unikalne częstotliwości (pasma) dla każdego systemu GNSS.
    W RINEX typ obserwacji koduje pasmo: C1C = L1 (1), C2I = L2 (2), C5Q = L5 (5) itd.
    Zwraca dict {sys_code: {'frequencies': [band_numbers], 'count': N}}.
    """
    sys_obs = header.get('sys_obs_types', {})
    result = {}
    # Mapowanie liter na pasma dla GPS/Galileo/GLONASS/BeiDou/QZSS/SBAS
    # Po pierwszej literze C/L/D/S, druga litera/cyfra to kod pasma
    # Typowo: 1=L1, 2=L2, 5=L5, 6=L6, 7=E5b, 8=E5a+b dla Galileo
    # Dla GLONASS: 1=L1, 2=L2, 3=L3
    for sys, obs_types in sys_obs.items():
        bands = set()
        for ot in obs_types:
            if len(ot) >= 2:
                # Druga litera/cyfra po C/L/D/S
                band_char = ot[1]
                # Konwertuj na numer pasma
                if band_char.isdigit():
                    band_num = int(band_char)
                else:
                    # Litery: A=1, B=2, C=3, X=5, Z=5 itd. - nieprecyzyjne
                    # Dla uproszczenia przypiszmy stałe
                    band_map = {'A': 1, 'B': 1, 'C': 1, 'D': 2, 'I': 2, 
                               'L': 2, 'M': 2, 'N': 2, 'P': 2, 'W': 2,
                               'X': 5, 'Q': 5, 'Z': 5, 'S': 5}
                    band_num = band_map.get(band_char.upper(), 0)
                if band_num > 0:
                    bands.add(band_num)
        result[sys] = {
            'frequencies': sorted(bands),
            'count': len(bands)
        }
    return result


def compute_multipath(epochs, header):
    """
    Oblicza multipath (MP) dla każdego satelity.
    MP = C - L*λ (różnica między pseudoodległością a fazą nośnej przeliczoną na metry)
    Dla GPS L1: λ = c/f1 ≈ 0.1903 m
    Dla GPS L2: λ = c/f2 ≈ 0.2442 m
    Dla GPS L5: λ = c/f5 ≈ 0.2548 m
    
    Zwraca listę (czas, sat, system, mp_value, mp_type).
    """
    from collections import defaultdict
    
    # Długości fal dla różnych systemów i pasm (w metrach)
    wavelengths = {
        ('G', '1'): 0.190293672798,  # GPS L1
        ('G', '2'): 0.244210213425,  # GPS L2
        ('G', '5'): 0.254828049,     # GPS L5
        ('R', '1'): 0.187136,        # GLONASS L1 (nominal)
        ('R', '2'): 0.240,           # GLONASS L2 (nominal)
        ('E', '1'): 0.190293672798,  # Galileo E1
        ('E', '5'): 0.254828049,     # Galileo E5a
        ('E', '7'): 0.248,           # Galileo E5b
        ('E', '6'): 0.233,           # Galileo E6
        ('E', '8'): 0.244,           # Galileo E5a+b
        ('C', '1'): 0.192,           # BeiDou B1
        ('C', '2'): 0.244,           # BeiDou B1-2
        ('C', '5'): 0.255,           # BeiDou B2a
        ('C', '6'): 0.234,           # BeiDou B3
        ('C', '7'): 0.248,           # BeiDou B2b
        ('J', '1'): 0.190293672798,  # QZSS L1
        ('J', '5'): 0.254828049,     # QZSS L5
        ('S', '1'): 0.190293672798,  # SBAS L1
        ('S', '5'): 0.254828049,     # SBAS L5
    }
    
    mp_data = []
    sys_obs = header.get('sys_obs_types', {})
    
    for t, obs in epochs:
        for sat, data in obs.items():
            sys_code = sat[0]
            if sys_code not in sys_obs:
                continue
            
            # Znajdź pary C* i L* dla tego samego pasma
            for obs_type in sys_obs[sys_code]:
                if obs_type.startswith('C') and len(obs_type) >= 2:
                    band = obs_type[1]
                    # Szukaj odpowiadającego L*
                    l_type = 'L' + obs_type[1:]
                    if l_type in data and obs_type in data:
                        C = data[obs_type]
                        L = data[l_type]
                        if not (math.isnan(C) or math.isnan(L) or C <= 0):
                            # Oblicz długość fali
                            wave_key = (sys_code, band)
                            wl = wavelengths.get(wave_key)
                            # Dla GLONASS spróbuj dokładniejszej wartości
                            if wl is None:
                                # Szacuj: L1 ~ 0.19m, L2 ~ 0.244m, L5 ~ 0.255m
                                if band == '1': wl = 0.19
                                elif band == '2': wl = 0.244
                                elif band == '5': wl = 0.255
                                elif band == '7': wl = 0.248
                                elif band == '6': wl = 0.234
                                elif band == '8': wl = 0.244
                                else: continue
                            
                            # MP = C - L * λ (w metrach)
                            mp = C - L * wl
                            mp_data.append((t, sat, sys_code, mp, 'MP_' + band))
    
    return mp_data


# ============================================================
# STATYSTYKI
# ============================================================

def compute_statistics(epochs, header, dop_data=None):
    """
    Oblicza statystyki dla danych obserwacyjnych.
    """
    stats = {}

    # Podstawowe informacje
    # Compute interval from epochs if not in header
    interval = header.get('interval', None)
    interval_note = ''
    if interval is None and epochs and len(epochs) >= 2:
        dt = (epochs[1][0] - epochs[0][0]).total_seconds()
        if dt > 0:
            interval = round(dt, 3)
            interval_note = 'computed from data'
    
    stats['file_info'] = {
        'marker': header.get('marker_name', 'N/A'),
        'receiver': header.get('rec_type', 'N/A'),
        'antenna': header.get('ant_type', 'N/A'),
        'approx_pos': header.get('approx_pos', None),
        'interval': interval,
        'interval_note': interval_note,
        'time_first': header.get('time_first', None),
        'time_last': header.get('time_last', None),
        'systems': list(header.get('sys_obs_types', {}).keys()),
        'obs_types': header.get('sys_obs_types', {}),
    }

    # Długość sesji
    if epochs:
        stats['duration'] = (epochs[-1][0] - epochs[0][0]).total_seconds()
    else:
        stats['duration'] = 0

    # Liczba epok
    stats['num_epochs'] = len(epochs)

    # Liczba satelitów
    sat_counts = [len(obs) for _, obs in epochs]
    if sat_counts:
        stats['sat_min'] = min(sat_counts)
        stats['sat_max'] = max(sat_counts)
        stats['sat_mean'] = np.mean(sat_counts)
        stats['sat_median'] = np.median(sat_counts)
        stats['sat_std'] = np.std(sat_counts)

        # Rozkład liczby satelitów
        all_counts = sorted(set(sat_counts))
        distribution = {}
        for c in all_counts:
            distribution[c] = sat_counts.count(c) / len(sat_counts) * 100
        stats['sat_distribution'] = distribution

        # Najczęstsza liczba satelitów
        max_count = max(distribution, key=distribution.get)
        stats['sat_most_common'] = max_count
        stats['sat_most_common_pct'] = distribution[max_count]

    # Liczba satelitów według systemu
    sys_counts = defaultdict(list)
    for _, obs in epochs:
        sys_count = defaultdict(int)
        for sat in obs:
            sys_count[sat[0]] += 1
        for sys, cnt in sys_count.items():
            sys_counts[sys].append(cnt)

    # Liczba częstotliwości (frequencies) dla każdego systemu
    freq_info = count_frequencies(header)
    
    stats['sys_stats'] = {}
    for sys, counts in sys_counts.items():
        sys_name = GNSS_SYSTEMS.get(sys, sys)
        if counts:
            sys_freq = freq_info.get(sys, {})
            stats['sys_stats'][sys_name] = {
                'min': min(counts),
                'max': max(counts),
                'mean': np.mean(counts),
                'total_epochs': len(counts),
                'frequencies': sys_freq.get('frequencies', []),
                'num_frequencies': sys_freq.get('count', 0),
            }

    # DOP statystyki
    if dop_data:
        pdop_vals = [d[1] for d in dop_data]
        hdop_vals = [d[2] for d in dop_data]
        vdop_vals = [d[3] for d in dop_data]
        gdop_vals = [d[4] for d in dop_data]

        stats['dop'] = {
            'PDOP_min': min(pdop_vals),
            'PDOP_max': max(pdop_vals),
            'PDOP_mean': np.mean(pdop_vals),
            'PDOP_median': np.median(pdop_vals),
            'HDOP_mean': np.mean(hdop_vals),
            'VDOP_mean': np.mean(vdop_vals),
            'GDOP_mean': np.mean(gdop_vals),
        }

    # SNR statystyki
    snr_data = analyze_snr(epochs, header)
    if snr_data:
        snr_vals = [s[3] for s in snr_data]
        stats['snr'] = {
            'min': min(snr_vals),
            'max': max(snr_vals),
            'mean': np.mean(snr_vals),
            'median': np.median(snr_vals),
        }

    # Liczba wszystkich zaobserwowanych satelitów
    all_sats = set()
    for _, obs in epochs:
        all_sats.update(obs.keys())
    stats['unique_satellites'] = len(all_sats)
    stats['satellites_list'] = sorted(all_sats)

    return stats


# ============================================================
# WYKRESY
# ============================================================

def plot_satellite_visibility(epochs, output_dir='.'):
    """
    Wykres widzialności satelitów w czasie.
    """
    visibility = analyze_satellite_visibility(epochs)
    times = [v[0] for v in visibility]
    total_sats = [v[1] for v in visibility]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(times, total_sats, 'b-', linewidth=1)
    ax.fill_between(times, total_sats, alpha=0.3, color='blue')
    ax.set_xlabel('Czas (GPS)')
    ax.set_ylabel('Liczba satelitów')
    ax.set_title('Widzialność satelitów (Satellite Visibility)')
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)

    # Dodaj średnią
    mean_val = np.mean(total_sats)
    ax.axhline(mean_val, color='red', linestyle='--', alpha=0.7,
               label=f'Średnia: {mean_val:.1f}')
    ax.legend()

    plt.tight_layout()
    path = os.path.join(output_dir, 'satellite_visibility.png')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Zapisano: {path}')
    return path


def plot_satellite_visibility_by_system(epochs, output_dir='.'):
    """
    Wykres widzialności według systemu GNSS.
    """
    visibility = analyze_satellite_visibility(epochs)
    times = [v[0] for v in visibility]
    sys_data = defaultdict(list)

    for v in visibility:
        for sys, cnt in v[2].items():
            sys_data[sys].append(cnt)

    fig, ax = plt.subplots(figsize=(12, 5))
    for sys, counts in sys_data.items():
        # Wyrównaj długość
        padded = counts + [0] * (len(times) - len(counts))
        sys_name = GNSS_SYSTEMS.get(sys, f'System {sys}')
        color = SYSTEM_COLORS.get(sys, '#888888')
        ax.plot(times, padded, label=sys_name, color=color, linewidth=1)

    ax.set_xlabel('Czas (GPS)')
    ax.set_ylabel('Liczba satelitów')
    ax.set_title('Widzialność według systemu GNSS')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=9)
    ax.set_ylim(bottom=0)

    plt.tight_layout()
    path = os.path.join(output_dir, 'satellite_visibility_by_system.png')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Zapisano: {path}')
    return path


def plot_skyplot(epochs, ephemerides, obs_pos, output_dir='.'):
    """
    Skyplot - azymut i elewacja wszystkich satelitów.
    Przeszukuje wszystkie epoki aby znaleźć każdy zaobserwowany satelita.
    """
    if not ephemerides or obs_pos is None:
        print('  Brak danych nawigacyjnych lub pozycji obserwatora - pomijam skyplot')
        return None

    # Znajdź epokę z największą liczbą satelitów
    best_epoch_idx = 0
    max_sats = 0
    for idx, (t, obs) in enumerate(epochs):
        if len(obs) > max_sats:
            max_sats = len(obs)
            best_epoch_idx = idx
    
    print(f'  Skyplot: używam epoki {best_epoch_idx} z {max_sats} satelitami')
    
    # Zbierz WSZYSTKIE unikalne satelity ze wszystkich epok
    all_unique_sats = set()
    for t, obs in epochs:
        all_unique_sats.update(obs.keys())
    print(f'  Skyplot: łącznie {len(all_unique_sats)} unikalnych satelitów do znalezienia')
    
    # Oblicz pozycje dla każdego unikalnego satelity
    all_positions = {}  # {sat: (az, el)}
    sat_colors = {}
    found_count = 0
    
    for sat in sorted(all_unique_sats):
        prn = sat
        sys_code = prn[0]
        
        # Znajdź najlepszą epokę dla tego satelity (gdzie jest widoczny)
        found = False
        for t, obs in epochs:
            if sat not in obs:
                continue
            
            matching_eph = [e for e in ephemerides if e.get('prn') == prn]
            if not matching_eph:
                continue
            best_eph = min(matching_eph, key=lambda e: abs((t - e['toc']).total_seconds()))
            
            sat_pos = compute_satellite_position(best_eph, (t - GPS_WEEK_EPOCH).total_seconds())
            if sat_pos is None:
                continue
            
            az, el = compute_azimuth_elevation(sat_pos, obs_pos)
            if az is not None and el is not None and el > 5:  # tylko nad horyzontem
                all_positions[prn] = (az, el)
                sat_colors[prn] = SYSTEM_COLORS.get(sys_code, '#888888')
                found = True
                found_count += 1
                break  # znaleźliśmy pozycję dla tego satelity
        
        if found_count > 0 and found_count % 10 == 0:
            print(f'  Skyplot: znaleziono {found_count}/{len(all_unique_sats)} satelitów...')

    if not all_positions:
        print('  Nie można obliczyć pozycji satelitów - pomijam skyplot')
        return None
    
    print(f'  Skyplot: wyświetlam {len(all_positions)} satelitów')

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={'projection': 'polar'})
    ax.set_theta_zero_location('N')  # Północ na górze
    ax.set_theta_direction(-1)        # Zgodnie z ruchem wskazówek
    ax.set_ylim(0, 90)
    
    # Rysuj okręgi elewacji z etykietami
    ax.set_yticks([15, 30, 45, 60, 75, 90])
    ax.set_yticklabels(['75°', '60°', '45°', '30°', '15°', '0°'])
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)

    for prn, (az, el) in all_positions.items():
        az_rad = math.radians(az)
        r = 90 - el  # promień od środka (0° = horyzont, 90° = zenit)
        color = sat_colors.get(prn, '#888888')
        ax.plot(az_rad, r, 'o', color=color, markersize=9, zorder=5)
        ax.annotate(prn, (az_rad, r), fontsize=8, ha='center', va='bottom',
                   color=color, fontweight='bold', zorder=6)

    ax.set_title('Skyplot (Azimuth / Elevation)', pad=20, fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.4, linestyle='--')

    plt.tight_layout()
    path = os.path.join(output_dir, 'skyplot.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'  Zapisano: {path}')
    return path


def plot_dop(epochs, ephemerides, obs_pos, output_dir='.'):
    """
    Wykres DOP (PDOP, HDOP, VDOP) i liczby satelitów.
    """
    if not ephemerides or obs_pos is None:
        print('  Brak danych nawigacyjnych lub pozycji - pomijam DOP')
        return None

    dop_data = compute_dop(epochs, ephemerides, obs_pos)
    if not dop_data:
        print('  Nie można obliczyć DOP - pomijam')
        return None

    times = [d[0] for d in dop_data]
    pdop = [d[1] for d in dop_data]
    hdop = [d[2] for d in dop_data]
    vdop = [d[3] for d in dop_data]
    nsat = [d[5] for d in dop_data]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Górny panel: DOP
    ax1.plot(times, pdop, 'r-', label='PDOP', linewidth=1)
    ax1.plot(times, hdop, 'g-', label='HDOP', linewidth=1)
    ax1.plot(times, vdop, 'b-', label='VDOP', linewidth=1)
    ax1.set_ylabel('DOP')
    ax1.set_title('DOP i liczba satelitów (DOP/NSat)')
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)

    # Dodaj średnią PDOP
    mean_pdop = np.mean(pdop)
    ax1.axhline(mean_pdop, color='red', linestyle='--', alpha=0.5,
                label=f'Średnia PDOP: {mean_pdop:.2f}')
    ax1.legend(fontsize=9)

    # Dolny panel: liczba satelitów
    ax2.plot(times, nsat, 'b-', linewidth=1)
    ax2.fill_between(times, nsat, alpha=0.3, color='blue')
    ax2.set_xlabel('Czas (GPS)')
    ax2.set_ylabel('Liczba satelitów')
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(bottom=0)

    plt.tight_layout()
    path = os.path.join(output_dir, 'dop_nsat.png')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Zapisano: {path}')
    return path


def plot_snr_time(epochs, header, output_dir='.'):
    """
    Wykres SNR w czasie dla każdego satelity.
    """
    snr_data = analyze_snr(epochs, header)
    if not snr_data:
        print('  Brak danych SNR - pomijam')
        return None

    # Grupuj według satelity
    sat_snr = defaultdict(list)
    for t, sat, sys_code, snr_val, obs_type in snr_data:
        sat_snr[sat].append((t, snr_val, obs_type))

    fig, ax = plt.subplots(figsize=(12, 6))

    colors = plt.cm.tab20(np.linspace(0, 1, len(sat_snr)))
    for idx, (sat, values) in enumerate(sorted(sat_snr.items())):
        times = [v[0] for v in values]
        snrs = [v[1] for v in values]
        obs_type = values[0][2] if values else ''
        # Uśrednij SNR dla każdego czasu (różne częstotliwości)
        # Dla każdego czasu, weź średnią
        time_groups = defaultdict(list)
        for t, snr_val, ot in values:
            time_groups[t].append(snr_val)
        avg_times = list(time_groups.keys())
        avg_snrs = [np.mean(time_groups[t]) for t in avg_times]

        sys_code = sat[0]
        color = SYSTEM_COLORS.get(sys_code, colors[idx])
        ax.plot(avg_times, avg_snrs, '.', markersize=3, color=color, label=sat)
        # Dodaj linię trendu
        if len(avg_times) > 1:
            z = np.polyfit(range(len(avg_times)), avg_snrs, 1)
            # Nie rysuj linii, tylko kropki

    ax.set_xlabel('Czas (GPS)')
    ax.set_ylabel('SNR (dBHz)')
    ax.set_title('Siła sygnału (SNR) w czasie')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=8, ncol=3)

    plt.tight_layout()
    path = os.path.join(output_dir, 'snr_time.png')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Zapisano: {path}')

    # Dodatkowy wykres: SNR vs czas dla wybranych systemów
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    axes = axes.flatten()
    sys_list = list(set(s[2] for s in snr_data))
    colors_list = [SYSTEM_COLORS.get(s, '#888888') for s in sys_list]

    for i, (sys_code, ax_i) in enumerate(zip(sys_list, axes)):
        sys_name = GNSS_SYSTEMS.get(sys_code, f'System {sys_code}')
        sys_snrs = [(t, sat, snr, ot) for t, sat, sc, snr, ot in snr_data if sc == sys_code]
        if not sys_snrs:
            ax_i.text(0.5, 0.5, 'Brak danych', ha='center', va='center')
            continue

        sat_groups = defaultdict(list)
        for t, sat, snr, ot in sys_snrs:
            sat_groups[sat].append((t, snr))

        for sat, values in sat_groups.items():
            times = [v[0] for v in values]
            snrs = [v[1] for v in values]
            ax_i.plot(times, snrs, '.', markersize=3, label=sat)
            # Uśrednione
            time_groups = defaultdict(list)
            for t, snr_val in values:
                time_groups[t].append(snr_val)
            avg_times = list(time_groups.keys())
            avg_snrs = [np.mean(time_groups[t]) for t in avg_times]
            ax_i.plot(avg_times, avg_snrs, '-', linewidth=0.8, alpha=0.5)

        ax_i.set_xlabel('Czas (GPS)')
        ax_i.set_ylabel('SNR (dBHz)')
        ax_i.set_title(f'{sys_name}')
        ax_i.grid(True, alpha=0.3)
        ax_i.legend(fontsize=6, ncol=2)

    # Ukryj nieużywane osie
    for i in range(len(sys_list), 4):
        axes[i].set_visible(False)

    fig.suptitle('SNR w czasie według systemu GNSS', fontsize=14)
    plt.tight_layout()
    path = os.path.join(output_dir, 'snr_time_by_system.png')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Zapisano: {path}')

    return path


def plot_snr_elevation(epochs, ephemerides, obs_pos, header, output_dir='.'):
    """
    Wykres SNR vs elewacja.
    """
    if not ephemerides or obs_pos is None:
        print('  Brak danych nawigacyjnych - pomijam SNR/EL')
        return None

    snr_data = analyze_snr(epochs, header)
    if not snr_data:
        print('  Brak danych SNR - pomijam')
        return None

    # Oblicz elewację dla każdego pomiaru SNR
    snr_el = []
    for t, sat, sys_code, snr_val, obs_type in snr_data:
        # Znajdź ephemeris
        matching_eph = [e for e in ephemerides if e.get('prn') == sat]
        if not matching_eph:
            continue
        best_eph = min(matching_eph, key=lambda e: abs((t - e['toc']).total_seconds()))
        sat_pos = compute_satellite_position(best_eph, (t - GPS_WEEK_EPOCH).total_seconds())
        if sat_pos is None:
            continue
        _, el = compute_azimuth_elevation(sat_pos, obs_pos)
        if el is not None and el > 0:
            snr_el.append((el, snr_val, sat, sys_code))

    if not snr_el:
        print('  Nie można obliczyć elewacji - pomijam SNR/EL')
        return None

    fig, ax = plt.subplots(figsize=(10, 6))

    # Grupuj według systemu
    sys_groups = defaultdict(list)
    for el, snr, sat, sys_code in snr_el:
        sys_groups[sys_code].append((el, snr, sat))

    for sys_code, values in sys_groups.items():
        sys_name = GNSS_SYSTEMS.get(sys_code, sys_code)
        color = SYSTEM_COLORS.get(sys_code, '#888888')
        el_vals = [v[0] for v in values]
        snr_vals = [v[1] for v in values]
        ax.plot(el_vals, snr_vals, '.', markersize=3, color=color, label=sys_name, alpha=0.5)

        # Dodaj linię trendu
        if len(el_vals) > 10:
            # Średnia w oknach elewacji
            bins = np.arange(0, 95, 5)
            bin_means = []
            bin_centers = []
            for i in range(len(bins) - 1):
                mask = (np.array(el_vals) >= bins[i]) & (np.array(el_vals) < bins[i + 1])
                if np.any(mask):
                    bin_means.append(np.mean(np.array(snr_vals)[mask]))
                    bin_centers.append((bins[i] + bins[i + 1]) / 2)
            if len(bin_means) > 1:
                ax.plot(bin_centers, bin_means, '-', color=color, linewidth=2, alpha=0.8)

    ax.set_xlabel('Elewacja (stopnie)')
    ax.set_ylabel('SNR (dBHz)')
    ax.set_title('SNR vs Elewacja')
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)

    plt.tight_layout()
    path = os.path.join(output_dir, 'snr_elevation.png')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Zapisano: {path}')
    return path


def print_statistics(stats):
    """
    Wyświetla statystyki w czytelny sposób.
    """
    print('\n' + '=' * 60)
    print('STATYSTYKI')
    print('=' * 60)

    info = stats.get('file_info', {})
    print(f'\n--- Informacje o pliku ---')
    print(f'  Znacznik: {info.get("marker", "N/A")}')
    print(f'  Odbiornik: {info.get("receiver", "N/A")}')
    print(f'  Antena: {info.get("antenna", "N/A")}')
    if info.get('approx_pos'):
        x, y, z = info['approx_pos']
        lat, lon, h = ecef_to_geodetic(x, y, z)
        print(f'  Przybliżona pozycja: X={x:.4f}, Y={y:.4f}, Z={z:.4f}')
        print(f'    Szerokość: {math.degrees(lat):.6f}°')
        print(f'    Długość: {math.degrees(lon):.6f}°')
        print(f'    Wysokość elipsoidalna: {h:.3f} m')
    if info.get('interval'):
        ival = info['interval']
        note = f' ({info.get("interval_note", "")})' if info.get('interval_note') else ''
        print(f'  Interwał: {ival} s{note}')
    if info.get('time_first'):
        print(f'  Czas rozpoczęcia: {info["time_first"]}')
    if info.get('time_last'):
        print(f'  Czas zakończenia: {info["time_last"]}')
    print(f'  Systemy: {", ".join(info.get("systems", []))}')
    print(f'  Typy obserwacji:')
    for sys, types in info.get('obs_types', {}).items():
        sys_name = GNSS_SYSTEMS.get(sys, sys)
        print(f'    {sys_name} ({sys}): {len(types)} typów - {", ".join(types)}')

    print(f'\n--- Ogólne ---')
    print(f'  Liczba epok: {stats.get("num_epochs", 0)}')
    dur = stats.get('duration', 0)
    hours = int(dur // 3600)
    minutes = int((dur % 3600) // 60)
    seconds = dur % 60
    print(f'  Czas trwania: {hours}h {minutes}m {seconds:.1f}s')
    print(f'  Unikalne satelity: {stats.get("unique_satellites", 0)}')
    print(f'  Lista satelitów: {", ".join(stats.get("satellites_list", []))}')

    print(f'\n--- Liczba satelitów ---')
    print(f'  Minimum: {stats.get("sat_min", 0)}')
    print(f'  Maksimum: {stats.get("sat_max", 0)}')
    print(f'  Średnia: {stats.get("sat_mean", 0):.2f}')
    print(f'  Mediana: {stats.get("sat_median", 0):.1f}')
    print(f'  Odchylenie standardowe: {stats.get("sat_std", 0):.2f}')
    print(f'  Najczęściej: {stats.get("sat_most_common", 0)} ({stats.get("sat_most_common_pct", 0):.1f}%)')
    print(f'  Rozkład:')
    for count, pct in sorted(stats.get('sat_distribution', {}).items()):
        bar = '█' * int(pct / 2)
        print(f'    {count:2d}: {pct:5.1f}% {bar}')

    sys_stats = stats.get('sys_stats', {})
    if sys_stats:
        print(f'\n--- Satelity według systemu ---')
        for sys_name, s in sorted(sys_stats.items()):
            print(f'  {sys_name}: min={s["min"]}, max={s["max"]}, śr={s["mean"]:.1f}')

    if 'dop' in stats:
        dop = stats['dop']
        print(f'\n--- DOP ---')
        print(f'  PDOP: min={dop["PDOP_min"]:.2f}, max={dop["PDOP_max"]:.2f}, '
              f'śr={dop["PDOP_mean"]:.2f}, mediana={dop["PDOP_median"]:.2f}')
        print(f'  HDOP: śr={dop["HDOP_mean"]:.2f}')
        print(f'  VDOP: śr={dop["VDOP_mean"]:.2f}')
        print(f'  GDOP: śr={dop["GDOP_mean"]:.2f}')

    if 'snr' in stats:
        snr = stats['snr']
        print(f'\n--- SNR ---')
        print(f'  Minimum: {snr["min"]:.1f} dBHz')
        print(f'  Maksimum: {snr["max"]:.1f} dBHz')
        print(f'  Średnia: {snr["mean"]:.1f} dBHz')
        print(f'  Mediana: {snr["median"]:.1f} dBHz')

    print('=' * 60)


# ============================================================
# GŁÓWNA FUNKCJA
# ============================================================

def find_nav_file(obs_file):
    """Szuka pliku nawigacyjnego odpowiadającego plikowi obserwacyjnemu."""
    base = os.path.splitext(obs_file)[0]
    dir_name = os.path.dirname(obs_file)
    obs_basename = os.path.basename(obs_file)

    # Typowe rozszerzenia plików nawigacyjnych
    nav_extensions = ['.nav', '.rnx', '.26n', '.26g', '.26l', '.26p', '.26f',
                      '.19n', '.19g', '.19l', '.19p', '.19f']
    obs_extensions = ['.obs', '.rnx', '.26o', '.27o', '.28o', '.29o']

    # Generuj potencjalne nazwy plików nawigacyjnych
    candidates = []
    
    # 1. Zamiana rozszerzenia (np. .26o -> .26n, .obs -> .nav)
    for obs_ext in obs_extensions:
        for nav_ext in nav_extensions:
            if obs_basename.endswith(obs_ext):
                candidates.append(obs_basename[:-len(obs_ext)] + nav_ext)
    
    # 2. Zamiana _MO na _MN (dla plików Septentrio: *_MO.rnx -> *_MN.rnx)
    if '_MO.' in obs_basename:
        candidates.append(obs_basename.replace('_MO.', '_MN.'))
    if '_MO' in obs_basename and '_MO.' not in obs_basename:
        # *_MO.rnx case -> *_MN.rnx
        candidates.append(obs_basename.replace('_MO', '_MN'))
    
    # 3. Dodaj .nav jako ogólne rozszerzenie nawigacyjne
    for ext in ['.nav']:
        candidates.append(os.path.splitext(obs_basename)[0] + ext)

    # Szukaj w tym samym katalogu
    if dir_name and os.path.isdir(dir_name):
        # Najpierw szukaj po potencjalnych nazwach
        for f in os.listdir(dir_name):
            fpath = os.path.join(dir_name, f)
            if not os.path.isfile(fpath):
                continue
            if f == obs_basename:
                continue  # pomiń samego siebie
            if f in candidates:
                return fpath
        
        # Potem szukaj po rozszerzeniu nawigacyjnym i podobieństwie nazw
        # Twórz listę dopasowań z wagami (im więcej wspólnych tokenów, tym lepiej)
        obs_tokens = set(re.split(r'[._]', obs_basename))
        matches = []
        
        for f in os.listdir(dir_name):
            fpath = os.path.join(dir_name, f)
            if not os.path.isfile(fpath):
                continue
            if f == obs_basename:
                continue
            
            ext = os.path.splitext(f)[1].lower()
            if ext not in nav_extensions:
                continue
            
            f_tokens = set(re.split(r'[._]', f))
            common = obs_tokens & f_tokens
            # Waga: liczba wspólnych tokenów + bonus za _MN (navigation)
            score = len(common)
            if '_MN' in f or '.nav' in f:
                score += 2
            if '_MO' in f:
                score -= 1
            matches.append((score, fpath))
        
        if matches:
            # Wybierz najlepsze dopasowanie
            matches.sort(key=lambda x: -x[0])
            if matches[0][0] > 1:  # przynajmniej 2 wspólne tokeny
                return matches[0][1]

    return None


def find_obs_files(path):
    """Znajduje pliki RINEX obserwacyjne w ścieżce."""
    obs_files = []

    if os.path.isfile(path):
        if is_rinex_obs_file(path):
            obs_files.append(path)
        return obs_files

    for root, dirs, files in os.walk(path):
        for f in files:
            fpath = os.path.join(root, f)
            if is_rinex_obs_file(fpath):
                obs_files.append(fpath)

    return obs_files


def is_rinex_obs_file(path):
    """Sprawdza czy plik jest plikiem RINEX obserwacyjnym."""
    # Sprawdź rozszerzenie
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.obs', '.rnx']:
        return True
    if re.match(r'\.\d+o$', ext):
        return True
    # Sprawdź zawartość
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            header = f.read(200)
            if 'OBSERVATION DATA' in header:
                return True
    except:
        pass
    return False


def main():
    if len(sys.argv) < 2:
        print('Użycie: python3 rinex_analyzer.py <plik_observacyjny> [plik_nawigacyjny]')
        print('  lub:  python3 rinex_analyzer.py <katalog_z_plikami>')
        print('\nJeśli nie podano pliku nawigacyjnego, skrypt szuka go automatycznie.')
        sys.exit(1)

    input_path = sys.argv[1]
    nav_file = sys.argv[2] if len(sys.argv) > 2 else None

    # Znajdź pliki obserwacyjne
    obs_files = find_obs_files(input_path)

    if not obs_files:
        print(f'Nie znaleziono plików RINEX obserwacyjnych w: {input_path}')
        sys.exit(1)

    print(f'Znaleziono {len(obs_files)} plików obserwacyjnych')

    for obs_file in obs_files:
        print(f'\n{"=" * 60}')
        print(f'Przetwarzanie: {obs_file}')
        print(f'{"=" * 60}')

        # Znajdź plik nawigacyjny
        if nav_file and os.path.exists(nav_file):
            nav_path = nav_file
        else:
            nav_path = find_nav_file(obs_file)
            if nav_path:
                print(f'  Znaleziono plik nawigacyjny: {os.path.basename(nav_path)}')

        # Parsuj plik obserwacyjny
        print('  Parsowanie pliku obserwacyjnego...')
        try:
            header, epochs = parse_rinex_obs(obs_file)
        except Exception as e:
            print(f'  BŁĄD: Nie można przetworzyć pliku: {e}')
            continue

        print(f'  Znaleziono {len(epochs)} epok')
        if not epochs:
            print('  Brak danych obserwacyjnych!')
            continue

        # Parsuj plik nawigacyjny
        ephemerides = []
        if nav_path and os.path.exists(nav_path):
            print('  Parsowanie pliku nawigacyjnego...')
            try:
                ephemerides, _, _, _ = parse_rinex_nav(nav_path)
                print(f'  Znaleziono {len(ephemerides)} ephemeris')
            except Exception as e:
                print(f'  Ostrzeżenie: Nie można przetworzyć pliku nawigacyjnego: {e}')

        # Pozycja obserwatora
        obs_pos = header.get('approx_pos')

        # Oblicz DOP jeśli mamy ephemeris
        dop_data = None
        if ephemerides and obs_pos:
            print('  Obliczanie DOP...')
            dop_data = compute_dop(epochs, ephemerides, obs_pos)
            if dop_data:
                print(f'  Obliczono DOP dla {len(dop_data)} epok')

        # Oblicz statystyki
        print('  Obliczanie statystyk...')
        stats = compute_statistics(epochs, header, dop_data)

        # Wyświetl statystyki
        print_statistics(stats)

        # Generuj wykresy
        print('\n  Generowanie wykresów...')

        # Przygotuj katalog wyjściowy
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

        print(f'\n  Wykresy zapisane w: {output_dir}')


if __name__ == '__main__':
    main()
