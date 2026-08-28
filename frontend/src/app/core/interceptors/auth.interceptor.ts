import { Injectable, inject } from '@angular/core';
import { HttpInterceptor, HttpRequest, HttpHandler, HttpEvent, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { AuthService } from '../services/auth.service';

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  private authService = inject(AuthService);

  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    const token = this.authService.getToken();
    const cloned = token
      ? req.clone({ setHeaders: { Authorization: `Token ${token}` } })
      : req;

    return next.handle(cloned).pipe(
      catchError((error: unknown) => {
        // The token expired (AUTH_TOKEN_EXPIRY_HOURS) or was otherwise
        // rejected server-side. Clear it and send the user back to /login
        // rather than leaving the app stuck making requests that will
        // always 401.
        if (error instanceof HttpErrorResponse && error.status === 401 && token) {
          this.authService.logout();
        }
        return throwError(() => error);
      })
    );
  }
}