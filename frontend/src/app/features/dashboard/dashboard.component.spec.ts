import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { of, NEVER } from 'rxjs';
import { DashboardComponent } from './dashboard.component';
import { EndpointService, Endpoint } from '../../core/services/endpoint.service';
import { CheckService, CheckResult } from '../../core/services/check.service';
import { AuthService } from '../../core/services/auth.service';

// ── Fixtures ────────────────────────────────────────────────────────────────

const mockEndpoint: Endpoint = {
  id: 'uuid-1',
  name: 'My Site',
  url: 'https://example.com',
  interval_minutes: 5,
  is_active: true,
  last_alert_sent_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const mockCheckUp: CheckResult = {
  id: 'c-1',
  endpoint: 'uuid-1',
  endpoint_name: 'My Site',
  status_code: 200,
  response_time_ms: 142,
  is_up: true,
  checked_at: '2026-01-01T00:01:00Z',
};

const mockCheckDown: CheckResult = { ...mockCheckUp, id: 'c-2', status_code: 503, is_up: false };

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeEndpointService(endpoints: Endpoint[] = []) {
  return {
    list:     () => of(endpoints),
    create:   vi.fn(() => of(mockEndpoint)),
    update:   vi.fn(() => of(mockEndpoint)),
    delete:   vi.fn(() => of(undefined)),
    checkNow: vi.fn(() => of({ status: 'check queued' })),
  };
}

function setup(
  endpoints: Endpoint[] = [],
  checks: CheckResult[]  = [],
): ComponentFixture<DashboardComponent> {
  TestBed.configureTestingModule({
    imports: [DashboardComponent],
    providers: [
      { provide: EndpointService, useValue: makeEndpointService(endpoints) },
      { provide: CheckService,    useValue: { list: () => of(checks) } },
      { provide: AuthService,     useValue: { logout: vi.fn() } },
      provideRouter([]),
      provideNoopAnimations(),
    ],
  });
  const fixture = TestBed.createComponent(DashboardComponent);
  fixture.detectChanges();
  return fixture;
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('DashboardComponent', () => {

  describe('initial render', () => {
    it('should create', () => {
      expect(setup().componentInstance).toBeTruthy();
    });

    it('shows a progress bar while data is loading', () => {
      TestBed.configureTestingModule({
        imports: [DashboardComponent],
        providers: [
          { provide: EndpointService, useValue: { list: () => NEVER } },
          { provide: CheckService,    useValue: { list: () => NEVER } },
          { provide: AuthService,     useValue: { logout: vi.fn() } },
          provideRouter([]),
          provideNoopAnimations(),
        ],
      });
      const fixture = TestBed.createComponent(DashboardComponent);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('mat-progress-bar')).not.toBeNull();
    });
  });

  describe('summary cards', () => {
    it('shows 0 for all counts when no endpoints exist', () => {
      const el: HTMLElement = setup([]).nativeElement;
      const bigNumbers = el.querySelectorAll('.big-number');
      expect(bigNumbers.length).toBe(3);
      bigNumbers.forEach(n => expect(n.textContent?.trim()).toBe('0'));
    });

    it('reflects the endpoint count in the Total card', () => {
      const el: HTMLElement = setup([mockEndpoint]).nativeElement;
      expect(el.querySelectorAll('.big-number')[0].textContent?.trim()).toBe('1');
    });

    it('counts only checked-up endpoints in the Up card', () => {
      const el: HTMLElement = setup([mockEndpoint], [mockCheckUp]).nativeElement;
      expect(el.querySelectorAll('.big-number')[1].textContent?.trim()).toBe('1');
    });

    it('does not count pending endpoints as Down', () => {
      // One endpoint, no checks yet — Down should be 0
      const el: HTMLElement = setup([mockEndpoint], []).nativeElement;
      expect(el.querySelectorAll('.big-number')[2].textContent?.trim()).toBe('0');
    });
  });

  describe('empty state', () => {
    it('shows an empty-state card when no endpoints exist', () => {
      const el: HTMLElement = setup([]).nativeElement;
      expect(el.querySelector('.empty-state')).not.toBeNull();
    });

    it('does not show the empty-state card when endpoints exist', () => {
      const el: HTMLElement = setup([mockEndpoint]).nativeElement;
      expect(el.querySelector('.empty-state')).toBeNull();
    });
  });

  describe('status display', () => {
    it('shows Pending for an endpoint with no check result', () => {
      const el: HTMLElement = setup([mockEndpoint], []).nativeElement;
      expect(el.querySelector('.status-pending')).not.toBeNull();
      expect(el.textContent).toContain('Pending');
    });

    it('shows Up with icon and text for a healthy endpoint', () => {
      const el: HTMLElement = setup([mockEndpoint], [mockCheckUp]).nativeElement;
      expect(el.querySelector('.status-up')).not.toBeNull();
      expect(el.textContent).toContain('Up');
    });

    it('shows Down with icon and text for a failing endpoint', () => {
      const el: HTMLElement = setup([mockEndpoint], [mockCheckDown]).nativeElement;
      expect(el.querySelector('.status-down')).not.toBeNull();
      expect(el.textContent).toContain('Down');
    });
  });

  describe('accessibility', () => {
    it('action buttons have descriptive aria-labels', () => {
      const el: HTMLElement = setup([mockEndpoint]).nativeElement;
      const buttons: NodeListOf<HTMLButtonElement> = el.querySelectorAll('[aria-label]');
      const labels = Array.from(buttons).map(b => b.getAttribute('aria-label') ?? '');
      expect(labels.some(l => l.includes('My Site'))).toBe(true);
    });
  });
});
